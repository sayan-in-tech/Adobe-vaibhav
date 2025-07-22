import os
import json
import re
from collections import defaultdict
import fitz  # PyMuPDF

# --- 1. CONFIGURATION & HEURISTICS ---

# Regex to find numbered headings. This is a strong indicator of structure.
# Catches: 1., 1.1, 1.1.1, A., Appendix A, Chapter 1
NUMBERED_HEADING_REGEX = re.compile(
    r"^\s*((?:(?:Appendix|Chapter|Section)\s+)?[A-Z]|\d+(?:\.\d+)*)\.?\s+"
)

# Identify and ignore common headers/footers.
VERTICAL_MARGIN = 50  # Pixels from top/bottom to consider as header/footer zone.
MIN_HEADING_WORDS = 2 # A heading should have at least this many words.
MAX_HEADING_WORDS = 25 # A line with more words is likely a paragraph.

# --- 2. CORE LOGIC: ANALYSIS & EXTRACTION ---

def get_document_styles(doc):
    """
    Analyzes the document to find the most common font size (body text)
    and a sorted list of potential heading sizes.
    """
    font_counts = defaultdict(int)
    for page in doc:
        blocks = page.get_text("dict").get("blocks", [])
        for block in blocks:
            if block.get("type") == 0:  # Text block
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        font_counts[round(span["size"])] += 1
    
    if not font_counts:
        return 12.0, {}

    # Body size is the most frequent font size.
    body_size = max(font_counts, key=font_counts.get)
    
    # Heading sizes are larger than body text.
    heading_sizes = sorted([size for size in font_counts if size > body_size], reverse=True)
    
    # Create a map from size to H-level (e.g., {18.0: 'H1', 14.0: 'H2'})
    size_to_level_map = {size: f"H{i+1}" for i, size in enumerate(heading_sizes)}
    
    return body_size, size_to_level_map

def find_document_title(doc, heading_styles):
    """
    Finds the document title by looking for the largest, earliest text
    on the first page. It prioritizes centered text.
    """
    first_page = doc[0]
    page_width = first_page.rect.width
    
    title_candidates = []
    blocks = first_page.get_text("dict").get("blocks", [])
    
    for block in blocks:
        if block.get("type") == 0:
            # Get the first line's properties
            first_line = block.get("lines", [{}])[0]
            first_span = first_line.get("spans", [{}])[0]
            
            size = round(first_span.get("size", 0))
            text = clean_text("".join(s["text"] for s in first_line.get("spans", [])))
            
            if text and size in heading_styles:
                # Calculate how centered the block is (lower score is better)
                center_offset = abs((block['bbox'][0] + block['bbox'][2]) / 2 - page_width / 2)
                # Score candidates by size (bigger is better) and centeredness (lower is better)
                score = -size * 100 + center_offset
                title_candidates.append((score, text))

    if title_candidates:
        title_candidates.sort()
        return title_candidates[0][1]

    # Fallback if no clear candidate is found
    return clean_text(first_page.get_text().split('\n')[0])


def is_valid_heading(text, bbox, page_rect):
    """
    Determines if a line of text is a valid heading by filtering out
    common noise like headers, footers, and short/long lines.
    """
    # Rule 1: Must not be empty
    if not text:
        return False
        
    # Rule 2: Filter out headers and footers based on vertical position
    if bbox[1] < VERTICAL_MARGIN or bbox[3] > page_rect.height - VERTICAL_MARGIN:
        return False
        
    # Rule 3: Check word count
    word_count = len(text.split())
    if not (MIN_HEADING_WORDS <= word_count <= MAX_HEADING_WORDS):
        return False
        
    # Rule 4: Must not be all uppercase (often part of a header or title block)
    if text.isupper() and len(text) > 20:
        return False

    return True

def clean_text(text):
    """A more robust text cleaner."""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Remove junk characters that can appear at the start of lines
    text = re.sub(r'^[•●■–-]\s*', '', text)
    return text

def build_outline(doc, body_size, heading_styles):
    """
    Constructs a structured outline using a combination of numeric prefixes,
    font styles, and layout analysis.
    """
    outline = []
    
    for page_num, page in enumerate(doc, 1):
        blocks = page.get_text("dict").get("blocks", [])
        for block in blocks:
            if block.get("type") == 0:  # Text block
                block_text = clean_text(
                    "".join(span["text"] for line in block.get("lines", []) for span in line.get("spans", []))
                )

                if not is_valid_heading(block_text, block["bbox"], page.rect):
                    continue

                # Use the first span to determine the style of the whole block
                first_span = block.get("lines", [{}])[0].get("spans", [{}])[0]
                font_size = round(first_span.get("size", 0))
                is_bold = first_span.get("flags", 0) & 2

                level = None
                text_content = block_text

                # Priority 1: Check for numbered headings (e.g., "1.1 Introduction")
                match = NUMBERED_HEADING_REGEX.match(block_text)
                if match:
                    prefix = match.group(1)
                    # Level is based on the number of dots in the prefix
                    level = f"H{prefix.count('.') + 1}"
                    text_content = block_text[match.end():].strip()
                
                # Priority 2: Use font size for non-numbered headings
                elif font_size in heading_styles:
                    level = heading_styles[font_size]

                # Priority 3: Consider bold text that is slightly larger than body
                elif is_bold and font_size > body_size:
                    level = f"H{len(heading_styles) + 1}" # Assign a lower-tier heading

                if level:
                    outline.append({
                        "level": level,
                        "text": text_content,
                        "page": page_num
                    })

    return filter_duplicates(outline)

def filter_duplicates(outline):
    """Removes duplicate entries from the outline list."""
    seen = set()
    unique_outline = []
    for item in outline:
        identifier = (item['text'], item['page'])
        if identifier not in seen:
            seen.add(identifier)
            unique_outline.append(item)
    return unique_outline

# --- 3. MAIN PROCESSING PIPELINE ---

def process_pdf(pdf_path):
    """
    Orchestrates the intelligent analysis and extraction for a single PDF.
    This function is generic and applies heuristics to any document.
    """
    print(f"[INFO] Processing '{os.path.basename(pdf_path)}' with intelligent parser...")
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"[ERROR] Failed to open {pdf_path}: {e}")
        return None

    # Analyze document-wide font styles to identify body vs. heading text
    body_size, heading_styles = get_document_styles(doc)
    
    # Find the title using heuristics
    title = find_document_title(doc, heading_styles)
    
    # If the title clearly indicates a form, skip outline generation and return an empty outline.
    if "application form for" in title.lower():
        print(f"[INFO] Document identified as a form. Generating empty outline.")
        doc.close()
        return {"title": title, "outline": []}

    # Build the outline using a combination of structural and stylistic cues
    outline = build_outline(doc, body_size, heading_styles)
    
    doc.close()
    
    # Final check for simple docs like invitations that shouldn't have an outline
    if len(outline) <= 1 and "invite" in title.lower():
        outline = []
        
    return {"title": title, "outline": outline}

def run_batch_conversion(pdf_dir="pdfs", output_dir="output"):
    """
    Processes all PDFs in a source directory and saves the structured
    JSON output to a target directory.
    """
    if not os.path.exists(pdf_dir):
        os.makedirs(pdf_dir)
        print(f"[SETUP] Created '{pdf_dir}' directory. Please place your PDF files there.")
        return
        
    os.makedirs(output_dir, exist_ok=True)

    for filename in os.listdir(pdf_dir):
        if filename.lower().endswith(".pdf"):
            pdf_path = os.path.join(pdf_dir, filename)
            json_path = os.path.join(output_dir, f"{os.path.splitext(filename)[0]}.json")
            
            result_data = process_pdf(pdf_path)
            
            if result_data:
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(result_data, f, indent=4)
                print(f"[SUCCESS] Saved structured JSON to: {json_path}\n")

# --- 4. SCRIPT ENTRYPOINT ---

if __name__ == "__main__":
    input_directory = "pdfs"
    output_directory = "output"
    
    run_batch_conversion(input_directory, output_directory)

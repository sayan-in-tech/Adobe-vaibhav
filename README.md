# PDF Outline Extractor

## Setup & Run

1. **Install dependencies:**
   ```sh
   pip install -r requirements.txt
   ```

2. **Start the server:**
   ```sh
   uvicorn main:app --reload
   ```

3. **Open the web UI:**
   Go to [http://localhost:8000](http://localhost:8000) in your browser.

---

## Docker Usage

1. **Build the Docker image:**
   ```sh
   docker build -t pdf-outline-extractor .
   ```

2. **Run the Docker container:**
   ```sh
   docker run -p 8000:8000 pdf-outline-extractor
   ```

3. **Access the app:**
   Open [http://localhost:8000](http://localhost:8000) in your browser. 
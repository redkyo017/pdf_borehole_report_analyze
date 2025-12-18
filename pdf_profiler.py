# pdf_profiler.py
import pdfplumber
import PyPDF2
from pathlib import Path
import json

def profile_pdf(pdf_path):
    """
    Quickly profile a PDF to understand its structure.
    """
    profile = {
        'filename': Path(pdf_path).name,
        'size_mb': Path(pdf_path).stat().st_size / (1024 * 1024),
        'pages': 0,
        'has_text': False,
        'has_tables': False,
        'text_sample': '',
        'table_pages': [],
        'potential_chemical_keywords': 0
    }
    
    try:
        # Basic info with PyPDF2
        with open(pdf_path, 'rb') as f:
            pdf = PyPDF2.PdfReader(f)
            profile['pages'] = len(pdf.pages)
            
            # Check metadata
            if pdf.metadata:
                profile['metadata'] = {
                    'title': pdf.metadata.get('/Title', 'N/A'),
                    'author': pdf.metadata.get('/Author', 'N/A'),
                    'creator': pdf.metadata.get('/Creator', 'N/A'),
                }
        
        # Detailed analysis with pdfplumber (first 10 pages only for speed)
        with pdfplumber.open(pdf_path) as pdf:
            pages_to_check = min(10, len(pdf.pages))
            all_text = ''
            
            for i, page in enumerate(pdf.pages[:pages_to_check]):
                # Extract text
                text = page.extract_text()
                if text:
                    profile['has_text'] = True
                    all_text += text + '\n'
                
                # Check for tables
                tables = page.extract_tables()
                if tables:
                    profile['has_tables'] = True
                    profile['table_pages'].append(i + 1)
            
            # Sample text (first 500 chars)
            profile['text_sample'] = all_text[:500] if all_text else 'NO TEXT EXTRACTED'
            
            # Look for chemical-related keywords
            keywords = ['mg/kg', 'ppm', 'µg/l', 'Lead', 'Arsenic', 'Benzene', 'borehole', 'BH']
            profile['potential_chemical_keywords'] = sum(
                all_text.lower().count(kw.lower()) for kw in keywords
            )
    
    except Exception as e:
        profile['error'] = str(e)
    
    return profile

def batch_profile(path_like):
    """
    Profile either a single PDF or every PDF within a directory.
    """
    results = []
    target = Path(path_like)
    
    if target.is_file() and target.suffix.lower() == '.pdf':
        pdf_files = [target]
    elif target.is_dir():
        pdf_files = sorted(target.glob('*.pdf'))
    else:
        raise FileNotFoundError(f"No PDF found at '{path_like}'")
    
    if not pdf_files:
        print(f"No PDF files found in {target.resolve()}")
        return results
    
    print(f"Found {len(pdf_files)} PDF file(s)")
    
    for pdf_path in pdf_files:
        print(f"Profiling: {pdf_path.name}...")
        profile = profile_pdf(str(pdf_path))
        results.append(profile)
    
    return results

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python pdf_profiler.py <path_to_pdf_or_directory>")
        sys.exit(1)
    
    directory = sys.argv[1]
    results = batch_profile(directory)
    
    # Save results
    with open('pdf_analysis_results.json', 'w') as f:
        json.dump(results, indent=2, fp=f)
    
    # Print summary
    print("\n=== SUMMARY ===")
    total = len(results)
    print(f"Total PDFs: {total}")
    
    if total:
        print(f"Average size: {sum(r['size_mb'] for r in results) / total:.2f} MB")
        print(f"Average pages: {sum(r['pages'] for r in results) / total:.0f}")
    else:
        print("Average size: N/A")
        print("Average pages: N/A")
    
    print(f"PDFs with text: {sum(1 for r in results if r['has_text'])}")
    print(f"PDFs with tables: {sum(1 for r in results if r['has_tables'])}")

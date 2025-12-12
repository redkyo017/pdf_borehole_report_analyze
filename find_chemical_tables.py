import pdfplumber
import re
from pathlib import Path

def find_chemical_data_pages(pdf_path):
    """
    Identify which pages likely contain chemical test data.
    """
    results = {
        'filename': Path(pdf_path).name,
        'chemical_pages': []
    }
    
    # Chemical indicators (broaden this list based on your analysis)
    indicators = [
        r'mg/kg', r'ppm', r'µg/l', r'ug/l',
        r'\bLead\b', r'\bArsenic\b', r'\bCadmium\b', r'\bChromium\b',
        r'\bBenzo', r'\bPAH\b', r'\bTPH\b',
        r'Detection Limit', r'Screening Level', r'Threshold'
    ]
    
    pattern = re.compile('|'.join(indicators), re.IGNORECASE)
    
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue
            
            # Count matches
            matches = pattern.findall(text)
            
            # Check for tables
            tables = page.extract_tables()
            
            if len(matches) > 5 and tables:  # Likely chemical data page
                results['chemical_pages'].append({
                    'page': i + 1,
                    'keyword_matches': len(matches),
                    'table_count': len(tables),
                    'preview': text[:200]
                })
    
    return results

if __name__ == "__main__":
    import sys
    import json
    
    if len(sys.argv) < 2:
        print("Usage: python find_chemical_tables.py <pdf_path>")
        sys.exit(1)
    
    result = find_chemical_data_pages(sys.argv[1])
    print(json.dumps(result, indent=2))

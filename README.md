# Research Extractor v2

Research Extractor v2 extracts structured fields from unseen research PDFs and research URLs.

## Output fields

The app returns exactly these fields:

- Title
- Publisher
- Date
- Sample
- Methodology
- Research Type
- Category
- Destination Focus
- Ethnicity Focus
- Traveler Market
- Data Points
- Conclusion

## How it works

The extractor uses a layered pipeline for better accuracy on unseen files:

1. Parse PDF or webpage text
2. Classify page roles such as cover, methodology, data-heavy, and conclusion
3. Extract rule-based candidates for stable fields
4. Use one grounded Gemini call for harder semantic fields
5. Arbitrate between rule-based and AI outputs

## Local run

Create a virtual environment, install requirements, and run Streamlit:

```bash
pip install -r requirements.txt
streamlit run app.py
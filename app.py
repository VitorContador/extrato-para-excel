import pdfplumber
import pandas as pd
import re
import streamlit as st
from io import BytesIO

# Configuração da Página
st.set_page_config(page_title="Conversor de Extrato", layout="wide")

class BaseParser:
    def __init__(self):
        self.date_pattern = re.compile(r'^\d{2}/\d{2}/\d{4}|\d{2}/\d{2}')
    def clean_value(self, value_str):
        if not value_str: return 0.0
        val = str(value_str).replace('.', '').replace(',', '.')
        try: return float(val)
        except: return 0.0
    def is_start_of_transaction(self, text):
        return bool(self.date_pattern.match(str(text).strip()))

class GenericParser(BaseParser):
    def parse(self, pdf_path):
        all_data = []
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                words = page.extract_words(keep_blank_chars=True, y_tolerance=3)
                if not words: continue
                current_row = None
                for word in words:
                    text, x0 = word['text'].strip(), word['x0']
                    if self.is_start_of_transaction(text):
                        if current_row: all_data.append(current_row)
                        current_row = {"Data": text, "Historico": "", "Valor": "", "Pagina": page_num, "Layout": "Genérico"}
                    elif current_row:
                        if x0 > 400: current_row["Valor"] += f" {text}"
                        else: current_row["Historico"] += f" {text}"
                if current_row: all_data.append(current_row)
        return self.post_process(all_data)

    def post_process(self, data):
        df = pd.DataFrame(data)
        if df.empty: return df
        df['Historico'] = df['Historico'].str.strip()
        df['Valor_Num'] = df['Valor'].str.replace(' ', '').str.strip().apply(self.clean_value)
        df['Entrada'] = df['Valor_Num'].apply(lambda x: x if x > 0 else 0)
        df['Saida'] = df['Valor_Num'].apply(lambda x: abs(x) if x < 0 else 0)
        return df[["Data", "Historico", "Valor_Num", "Entrada", "Saida", "Pagina", "Layout"]]

# Interface Streamlit
st.title("🏦 Conversor de Extrato Bancário")
uploaded_file = st.file_uploader("Arraste o PDF aqui", type="pdf")

if uploaded_file:
    parser = GenericParser()
    df = parser.parse(uploaded_file)
    if not df.empty:
        st.success(f"Lançamentos encontrados: {len(df)}")
        edited_df = st.data_editor(df, use_container_width=True)
        col1, col2 = st.columns(2)
        
        output_excel = BytesIO()
        with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
            edited_df.to_excel(writer, index=False)
        col1.download_button("📥 Baixar Excel", output_excel.getvalue(), "extrato.xlsx")
        
        output_csv = edited_df.to_csv(index=False).encode('utf-8-sig')
        col2.download_button("📥 Baixar CSV", output_csv, "extrato.csv")
    else:
        st.error("Nenhum dado encontrado no PDF.")

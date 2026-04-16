import pdfplumber
import pandas as pd
import re
import streamlit as st
from io import BytesIO

st.set_page_config(page_title="Conversor de Extrato", layout="wide")

class BaseParser:
    def __init__(self):
        # Aceita datas: 02 OUT 2025, 02/10/2025, 02/10
        self.date_pattern = re.compile(r'^(\d{2}/\d{2}/\d{4}|\d{2}/\d{2}|\d{2}\s[A-Z]{3})')
    
    def clean_value(self, value_str):
        if not value_str: return 0.0
        # Remove R$, espaços e ajusta pontuação brasileira
        val = str(value_str).replace('R$', '').replace(' ', '').strip()
        if ',' in val:
            val = val.replace('.', '').replace(',', '.')
        try:
            return float(val)
        except:
            return 0.0

    def is_start_of_transaction(self, text):
        return bool(self.date_pattern.match(str(text).strip()))

class GenericParser(BaseParser):
    def parse(self, pdf_path):
        all_data = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                words = page.extract_words(keep_blank_chars=True, y_tolerance=3, x_tolerance=3)
                if not words: continue
                
                current_row = None
                for obj in words:
                    text, x0 = obj['text'].strip(), obj['x0']
                    
                    if self.is_start_of_transaction(text):
                        if current_row: all_data.append(current_row)
                        current_row = {"Data": text, "Historico": "", "Valor": "", "Pagina": page.page_number}
                    elif current_row:
                        # Se o texto tem número e vírgula, tratamos como potencial valor
                        # Reduzi o x0 para 250 para pegar colunas mais centrais se necessário
                        is_numeric = any(char.isdigit() for char in text) and ',' in text
                        if x0 > 250 and (is_numeric or 'R$' in text or '-' in text):
                            current_row["Valor"] += f" {text}"
                        else:
                            current_row["Historico"] += f" {text}"
                
                if current_row: all_data.append(current_row)
        return self.post_process(all_data)

    def post_process(self, data):
        df = pd.DataFrame(data)
        if df.empty: return df
        df['Historico'] = df['Historico'].str.replace('Total de entradas', '').replace('Total de saídas', '').strip()
        df['Valor_Num'] = df['Valor'].apply(self.clean_value)
        # Se o valor for 0 mas tiver algo no campo Valor, tentamos uma limpeza extra
        return df[["Data", "Historico", "Valor_Num", "Pagina"]]

st.title("🏦 Conversor de Extrato Bancário")
uploaded_file = st.file_uploader("Arraste o PDF aqui", type="pdf")

if uploaded_file:
    with st.spinner('Processando...'):
        parser = GenericParser()
        df = parser.parse(uploaded_file)
        if not df.empty:
            st.success(f"Lançamentos processados: {len(df)}")
            # O data_editor permite que você ajuste valores manualmente se algum falhar
            edited_df = st.data_editor(df, use_container_width=True, num_rows="dynamic")
            
            output_excel = BytesIO()
            with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
                edited_df.to_excel(writer, index=False)
            st.download_button("📥 Baixar Excel", output_excel.getvalue(), "extrato_vitor.xlsx")

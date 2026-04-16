import pdfplumber
import pandas as pd
import re
import streamlit as st
from io import BytesIO

st.set_page_config(page_title="Conversor de Extrato", layout="wide")

class BaseParser:
    def __init__(self):
        self.date_pattern = re.compile(r'^(\d{2}/\d{2}/\d{4}|\d{2}/\d{2}|\d{2}\s[A-Z]{3})')
    
    def clean_value(self, value_str):
        if not value_str: return 0.0
        # Remove R$, espaços e pontos de milhar, troca vírgula por ponto
        val = str(value_str).replace('R$', '').replace(' ', '').replace('.', '').replace(',', '.').strip()
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
            for page_num, page in enumerate(pdf.pages, 1):
                words = page.extract_words(keep_blank_chars=True, y_tolerance=3)
                if not words: continue
                
                current_row = None
                for obj in words:
                    text, x0 = obj['text'].strip(), obj['x0']
                    
                    if self.is_start_of_transaction(text):
                        if current_row: all_data.append(current_row)
                        current_row = {"Data": text, "Historico": "", "Valor": "", "Pagina": page_num}
                    elif current_row:
                        # Se o texto tem cara de dinheiro e está à direita, é Valor
                        if x0 > 300 and (',' in text or 'R$' in text):
                            current_row["Valor"] += f" {text}"
                        else:
                            current_row["Historico"] += f" {text}"
                
                if current_row: all_data.append(current_row)
        return self.post_process(all_data)

    def post_process(self, data):
        df = pd.DataFrame(data)
        if df.empty: return df
        df['Historico'] = df['Historico'].str.strip()
        df['Valor_Num'] = df['Valor'].apply(self.clean_value)
        # Classificação simples: se no histórico tiver "Recebida" ou "Depósito" costuma ser entrada
        # Mas vamos focar no valor bruto primeiro
        df['Entrada'] = df['Valor_Num'].apply(lambda x: x if x > 0 else 0)
        df['Saida'] = df['Valor_Num'].apply(lambda x: abs(x) if x < 0 else 0)
        return df[["Data", "Historico", "Valor_Num", "Pagina"]]

st.title("🏦 Conversor de Extrato Bancário")
uploaded_file = st.file_uploader("Arraste o PDF aqui", type="pdf")

if uploaded_file:
    parser = GenericParser()
    df = parser.parse(uploaded_file)
    if not df.empty:
        st.success(f"Encontramos {len(df)} lançamentos!")
        # Permitir que o usuário edite os valores se o sinal vier errado
        edited_df = st.data_editor(df, use_container_width=True)
        
        output_excel = BytesIO()
        with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
            edited_df.to_excel(writer, index=False)
        st.download_button("📥 Baixar Excel", output_excel.getvalue(), "extrato.xlsx")
    else:
        st.error("Não foi possível extrair os valores. Tente outro arquivo.")

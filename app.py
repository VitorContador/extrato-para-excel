import pdfplumber
import pandas as pd
import re
import streamlit as st
from io import BytesIO

st.set_page_config(page_title="Conversor de Extrato", layout="wide")

class BaseParser:
    def __init__(self):
        # Regex para datas (02 OUT 2025, 02/10/2025, etc)
        self.date_pattern = re.compile(r'^(\d{2}/\d{2}/\d{4}|\d{2}/\d{2}|\d{2}\s[A-Z]{3})')
    
    def clean_value(self, value_str):
        if not value_str: return 0.0
        # Limpa R$, espaços e ajusta pontos/vírgulas
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
                words = page.extract_words(keep_blank_chars=True, y_tolerance=3, x_tolerance=2)
                if not words: continue
                
                current_row = None
                for obj in words:
                    text, x0 = obj['text'].strip(), obj['x0']
                    
                    if self.is_start_of_transaction(text):
                        if current_row: all_data.append(current_row)
                        current_row = {"Data": text, "Historico": "", "Valor": "", "Pagina": page.page_number}
                    elif current_row:
                        # Se tem número e vírgula, ou sinal de menos, tratamos como valor
                        # Baixei o x0 para 200 para garantir que pegue colunas centrais
                        is_numeric = any(char.isdigit() for char in text) and ',' in text
                        if x0 > 200 and (is_numeric or 'R$' in text or (text.startswith('-') and len(text) > 1)):
                            current_row["Valor"] += f" {text}"
                        else:
                            current_row["Historico"] += f" {text}"
                
                if current_row: all_data.append(current_row)
        return self.post_process(all_data)

    def post_process(self, data):
        df = pd.DataFrame(data)
        if df.empty: return df
        
        # CORREÇÃO DO ERRO: Primeiro garantimos que a coluna é String, depois limpamos
        df['Historico'] = df['Historico'].astype(str).str.replace('Total de entradas', '', case=False)
        df['Historico'] = df['Historico'].str.replace('Total de saídas', '', case=False).str.strip()
        
        df['Valor_Num'] = df['Valor'].apply(self.clean_value)
        
        # Criando colunas de Entrada e Saída para facilitar sua vida
        df['Entrada'] = df['Valor_Num'].apply(lambda x: x if x > 0 else 0)
        df['Saida'] = df['Valor_Num'].apply(lambda x: abs(x) if x < 0 else 0)
        
        return df[["Data", "Historico", "Entrada", "Saida", "Valor_Num", "Pagina"]]

st.title("🏦 Conversor de Extrato Bancário")
uploaded_file = st.file_uploader("Arraste o PDF aqui", type="pdf")

if uploaded_file:
    with st.spinner('Processando extrato...'):
        parser = GenericParser()
        df = parser.parse(uploaded_file)
        if not df.empty:
            st.success(f"Encontramos {len(df)} lançamentos!")
            # O data_editor permite que você corrija qualquer valor na hora
            edited_df = st.data_editor(df, use_container_width=True, num_rows="dynamic")
            
            output_excel = BytesIO()
            with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
                edited_df.to_excel(writer, index=False)
            
            st.download_button("📥 Baixar Excel Completo", output_excel.getvalue(), "extrato_vitor_corrigido.xlsx")
        else:
            st.error("Nenhum dado encontrado. Verifique se o PDF é digital.")

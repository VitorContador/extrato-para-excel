import pdfplumber
import pandas as pd
import re
import streamlit as st
from io import BytesIO

st.set_page_config(page_title="Conversor de Extrato", layout="wide")

class BaseParser:
    def __init__(self):
        # Regex melhorada para datas (01/01/2024 ou 01 JAN)
        self.date_pattern = re.compile(r'^(\d{2}/\d{2}/\d{4}|\d{2}/\d{2}|\d{2}\s[A-Z]{3})')
    
    def clean_value(self, value_str):
        if not value_str: return 0.0
        # Remove símbolos de moeda e limpa espaços
        val = str(value_str).replace('R$', '').replace(' ', '').strip()
        # Trata o padrão brasileiro (milhar com ponto, decimal com vírgula)
        if ',' in val and '.' in val:
            val = val.replace('.', '').replace(',', '.')
        elif ',' in val:
            val = val.replace(',', '.')
        try: return float(val)
        except: return 0.0

    def is_start_of_transaction(self, text):
        return bool(self.date_pattern.match(str(text).strip()))

class GenericParser(BaseParser):
    def parse(self, pdf_path):
        all_data = []
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                # O segredo: extrair texto mantendo a ordem visual
                text_objects = page.extract_words(keep_blank_chars=True, y_tolerance=3, x_tolerance=3)
                if not text_objects: continue
                
                current_row = None
                for obj in text_objects:
                    text, x0 = obj['text'].strip(), obj['x0']
                    
                    if self.is_start_of_transaction(text):
                        if current_row: all_data.append(current_row)
                        current_row = {"Data": text, "Historico": "", "Valor": "", "Pagina": page_num}
                    elif current_row:
                        # Se o texto estiver muito à direita, é valor
                        if x0 > 350: 
                            current_row["Valor"] += f"{text}"
                        else:
                            current_row["Historico"] += f" {text}"
                
                if current_row: all_data.append(current_row)
        
        return self.post_process(all_data)

    def post_process(self, data):
        df = pd.DataFrame(data)
        if df.empty: return df
        df['Historico'] = df['Historico'].str.strip()
        # Limpa o valor e converte para número
        df['Valor_Num'] = df['Valor'].apply(self.clean_value)
        # Classifica Entrada/Saída (Ajuste para extratos que usam sinal de -)
        df['Entrada'] = df['Valor_Num'].apply(lambda x: x if x > 0 else 0)
        df['Saida'] = df['Valor_Num'].apply(lambda x: abs(x) if x < 0 else 0)
        return df[["Data", "Historico", "Valor_Num", "Entrada", "Saida", "Pagina"]]

st.title("🏦 Conversor de Extrato Bancário")
st.info("Dica: Este conversor funciona melhor com PDFs digitais (baixados do App/Site).")

uploaded_file = st.file_uploader("Arraste o PDF do Nubank ou outro banco aqui", type="pdf")

if uploaded_file:
    with st.spinner('Lendo lançamentos...'):
        parser = GenericParser()
        df = parser.parse(uploaded_file)
        
        if not df.empty:
            st.success(f"Sucesso! Encontramos {len(df)} lançamentos.")
            # Interface de edição
            edited_df = st.data_editor(df, use_container_width=True, num_rows="dynamic")
            
            col1, col2 = st.columns(2)
            output_excel = BytesIO()
            with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
                edited_df.to_excel(writer, index=False)
            col1.download_button("📥 Baixar Excel (.xlsx)", output_excel.getvalue(), "extrato_contabil.xlsx")
            
            output_csv = edited_df.to_csv(index=False).encode('utf-8-sig')
            col2.download_button("📥 Baixar CSV", output_csv, "extrato_contabil.csv")
        else:
            st.warning("Ainda não conseguimos detectar os dados. Verifique se o PDF não é uma imagem protegida.")

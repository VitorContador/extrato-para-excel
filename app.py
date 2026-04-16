import pdfplumber
import pandas as pd
import re
import streamlit as st
from io import BytesIO

st.set_page_config(page_title="Conversor Profissional - Vitor", layout="wide")

class NubankMasterParser:
    def __init__(self):
        # Regex para datas do Nubank (ex: 02 OUT 2025)
        self.date_pattern = re.compile(r'^\d{2}\s[A-Z]{3}')

    def clean_val(self, val_str):
        if not val_str: return 0.0
        # Limpeza agressiva: mantém apenas números, vírgula, ponto e sinal de menos
        clean = re.sub(r'[^0-9,\.\-]', '', str(val_str))
        if ',' in clean:
            clean = clean.replace('.', '').replace(',', '.')
        try: return float(clean)
        except: return 0.0

    def parse(self, pdf_file):
        extracted_rows = []
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                # Extrai palavras com coordenadas
                words = page.extract_words(keep_blank_chars=True, y_tolerance=3)
                
                current_tx = None
                for w in words:
                    text = w['text'].strip()
                    x0 = w['x0']
                    
                    # 1. Detecta Início de Transação (Data)
                    if self.date_pattern.match(text):
                        if current_tx: extracted_rows.append(current_tx)
                        current_tx = {
                            "Data": text, 
                            "Historico": "", 
                            "Valor_Raw": "", 
                            "Pagina": page.page_number
                        }
                    
                    elif current_tx:
                        # 2. Detecta se é Valor (Geralmente à direita, x0 > 380 no Nubank)
                        # Ou se contém símbolos financeiros específicos
                        if x0 > 380 or text.startswith('+') or text.startswith('-'):
                            # Acumula tudo que for valor (sinal + número)
                            current_tx["Valor_Raw"] += text
                        else:
                            # 3. Acumula Histórico
                            if text not in ["Total de entradas", "Total de saídas"]:
                                current_tx["Historico"] += f" {text}"
                
                if current_tx: extracted_rows.append(current_tx)
        
        return self.process_to_df(extracted_rows)

    def process_to_df(self, rows):
        df = pd.DataFrame(rows)
        if df.empty: return df
        
        # Converte valores brutos para colunas contábeis
        df['Valor_Final'] = df['Valor_Raw'].apply(self.clean_val)
        df['Entrada'] = df.apply(lambda r: r['Valor_Final'] if '+' in r['Valor_Raw'] or r['Valor_Final'] > 0 else 0, axis=1)
        df['Saida'] = df.apply(lambda r: abs(r['Valor_Final']) if '-' in r['Valor_Raw'] or r['Valor_Final'] < 0 else 0, axis=1)
        
        return df[["Data", "Historico", "Entrada", "Saida", "Pagina"]]

# --- Interface com Função Desfazer ---
st.title("🏦 Conversor Nubank → Excel (v4)")

if 'data' not in st.session_state: st.session_state.data = None
if 'history' not in st.session_state: st.session_state.history = []

file = st.file_uploader("Selecione o PDF do Nubank", type="pdf")

if file and st.session_state.data is None:
    parser = NubankMasterParser()
    df_result = parser.parse(file)
    st.session_state.data = df_result
    st.session_state.history.append(df_result.copy())

if st.session_state.data is not None:
    col_undo, col_save = st.columns([1, 5])
    
    if col_undo.button("⬅️ Desfazer (Ctrl+Z)"):
        if len(st.session_state.history) > 1:
            st.session_state.history.pop()
            st.session_state.data = st.session_state.history[-1].copy()
            st.rerun()

    # Editor de dados com suporte a Ctrl+Z nativo
    new_data = st.data_editor(st.session_state.data, use_container_width=True, num_rows="dynamic")

    if not new_data.equals(st.session_state.data):
        st.session_state.history.append(new_data.copy())
        st.session_state.data = new_data

    # Download
    xlsx = BytesIO()
    with pd.ExcelWriter(xlsx, engine='openpyxl') as writer:
        new_data.to_excel(writer, index=False)
    st.download_button("📥 Baixar Excel Corrigido", xlsx.getvalue(), "extrato_nubank.xlsx")

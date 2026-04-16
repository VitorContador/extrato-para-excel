import pdfplumber
import pandas as pd
import re
import streamlit as st
from io import BytesIO

st.set_page_config(page_title="Conversor Pro - Vitor", layout="wide")

# --- LÓGICA DE PARSER ---
class NubankParser:
    def __init__(self):
        # Regex para datas do Nubank: "02 OUT", "15 JAN", etc.
        self.date_pattern = re.compile(r'^\d{2}\s[A-Z]{3}')

    def clean_value(self, value_str):
        if not value_str: return 0.0
        # Remove R$, espaços, pontos de milhar e ajusta vírgula
        val = str(value_str).replace('R$', '').replace(' ', '').replace('.', '').replace(',', '.').strip()
        try:
            return float(val)
        except:
            return 0.0

    def parse(self, pdf_path):
        all_data = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                words = page.extract_words(keep_blank_chars=True, y_tolerance=3)
                if not words: continue
                
                current_row = None
                for obj in words:
                    text, x0 = obj['text'].strip(), obj['x0']
                    
                    # Identifica início de linha por data
                    if self.date_pattern.match(text):
                        if current_row: all_data.append(current_row)
                        current_row = {"Data": text, "Historico": "", "Valor_Bruto": "", "Pagina": page.page_number}
                    elif current_row:
                        # No Nubank, valores ficam geralmente após a coordenada 300
                        # Capturamos tudo que contém números, vírgulas ou sinais na parte direita
                        if x0 > 300 and (any(c.isdigit() for c in text) or '-' in text or 'R$' in text):
                            current_row["Valor_Bruto"] += f"{text}"
                        else:
                            current_row["Historico"] += f" {text}"
                
                if current_row: all_data.append(current_row)
        
        return self.post_process(all_data)

    def post_process(self, data):
        df = pd.DataFrame(data)
        if df.empty: return df
        df['Historico'] = df['Historico'].astype(str).str.strip()
        df['Valor_Final'] = df['Valor_Bruto'].apply(self.clean_value)
        
        # Separando Entrada e Saída baseado no sinal de negativo do PDF
        df['Entrada'] = df.apply(lambda x: x['Valor_Final'] if '-' not in x['Valor_Bruto'] else 0, axis=1)
        df['Saida'] = df.apply(lambda x: abs(x['Valor_Final']) if '-' in x['Valor_Bruto'] else 0, axis=1)
        
        return df[["Data", "Historico", "Entrada", "Saida", "Pagina"]]

# --- INTERFACE E FUNÇÃO DESFAZER ---
st.title("🏦 Conversor de Extrato Profissional")
st.markdown("Suporte a Ctrl+Z e detecção inteligente de valores.")

if 'df' not in st.session_state:
    st.session_state.df = None
if 'history' not in st.session_state:
    st.session_state.history = []

uploaded_file = st.file_uploader("Arraste o PDF do Nubank aqui", type="pdf")

if uploaded_file:
    if st.session_state.df is None:
        parser = NubankParser()
        st.session_state.df = parser.parse(uploaded_file)
        st.session_state.history.append(st.session_state.df.copy())

if st.session_state.df is not None:
    # Botão de Desfazer Visual (O Streamlit nativamente suporta Ctrl+Z no editor)
    if st.button("⬅️ Desfazer última alteração"):
        if len(st.session_state.history) > 1:
            st.session_state.history.pop()
            st.session_state.df = st.session_state.history[-1].copy()
            st.rerun()

    st.subheader("Lançamentos Extraídos")
    # O st.data_editor já possui suporte nativo a Ctrl+Z para desfazer edições nas células!
    edited_df = st.data_editor(
        st.session_state.df, 
        use_container_width=True, 
        num_rows="dynamic",
        key="editor"
    )

    # Atualiza histórico se houve mudança
    if not edited_df.equals(st.session_state.df):
        st.session_state.df = edited_df
        st.session_state.history.append(edited_df.copy())

    # Exportação
    col1, col2 = st.columns(2)
    output_excel = BytesIO()
    with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
        edited_df.to_excel(writer, index=False)
    
    col1.download_button("📥 Baixar Excel", output_excel.getvalue(), "extrato_vitor.xlsx")
    st.success("Dica: Você pode usar Ctrl+Z dentro da tabela para desfazer o que digitou!")

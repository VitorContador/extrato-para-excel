import pdfplumber
import pandas as pd
import re
import streamlit as st
from io import BytesIO

st.set_page_config(page_title="Conversor Profissional - Vitor", layout="wide")

class NubankUltraParser:
    def __init__(self):
        # Regex para datas: "02 OUT 2025" ou "02 OUT"
        self.date_pattern = re.compile(r'^\d{2}\s[A-Z]{3}')
        # Palavras para ignorar (sujeira de rodapé/institucional)
        self.blacklist = ["atendimento", "ouvidoria", "mande uma mensagem", "duvida", "ligue", "gerado dia", "nubank.com.br"]

    def clean_val(self, val_str):
        if not val_str: return 0.0
        # Remove R$, espaços e ajusta pontuação brasileira
        clean = re.sub(r'[^0-9,\.\-]', '', str(val_str))
        if ',' in clean:
            clean = clean.replace('.', '').replace(',', '.')
        try: 
            # Garante apenas 2 casas decimais para evitar "grudar" com número de página
            val = float(clean)
            return round(val, 2)
        except: return 0.0

    def parse(self, pdf_file):
        extracted_rows = []
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                words = page.extract_words(keep_blank_chars=True, y_tolerance=3)
                
                current_tx = None
                for w in words:
                    text = w['text'].strip()
                    x0 = w['x0']
                    
                    # Ignora linhas de rodapé
                    if any(word in text.lower() for word in self.blacklist):
                        continue

                    # 1. Detecta Início de Transação pela Data
                    if self.date_pattern.match(text):
                        if current_tx: extracted_rows.append(current_tx)
                        current_tx = {"Data": text, "Historico": "", "Valor_Raw": "", "Pagina": page.page_number}
                    
                    elif current_tx:
                        # 2. Detecta Valor (Foca na coluna da direita e ignora números isolados pequenos)
                        # No Nubank, valores reais com centavos sempre tem vírgula
                        if x0 > 380 and (',' in text or text.startswith('+') or text.startswith('-')):
                            # Se o valor já tem centavos, não deixa grudar mais nada (evita número de página)
                            if not ('.' in current_tx["Valor_Raw"] or ',' in current_tx["Valor_Raw"]):
                                current_tx["Valor_Raw"] += text
                        else:
                            # 3. Acumula Histórico (Evita frases institucionais)
                            if len(text) > 1 and text not in ["Total", "entradas", "saídas", "de"]:
                                current_tx["Historico"] += f" {text}"
                
                if current_tx: extracted_rows.append(current_tx)
        
        return self.process_to_df(extracted_rows)

    def process_to_df(self, rows):
        df = pd.DataFrame(rows)
        if df.empty: return df
        
        df['Historico'] = df['Historico'].astype(str).str.strip()
        df['Valor_Final'] = df['Valor_Raw'].apply(self.clean_val)
        
        # Identifica sinal pelo texto bruto
        df['Entrada'] = df.apply(lambda r: r['Valor_Final'] if '+' in r['Valor_Raw'] or r['Valor_Final'] > 0 else 0, axis=1)
        df['Saida'] = df.apply(lambda r: abs(r['Valor_Final']) if '-' in r['Valor_Raw'] or r['Valor_Final'] < 0 else 0, axis=1)
        
        return df[["Data", "Historico", "Entrada", "Saida", "Pagina"]]

# --- Interface ---
st.title("🏦 Conversor Nubank Premium")

if 'data' not in st.session_state: st.session_state.data = None
if 'history' not in st.session_state: st.session_state.history = []

file = st.file_uploader("Arraste o extrato aqui", type="pdf")

if file and st.session_state.data is None:
    st.session_state.data = NubankUltraParser().parse(file)
    st.session_state.history.append(st.session_state.data.copy())

if st.session_state.data is not None:
    if st.button("⬅️ Desfazer (Ctrl+Z)"):
        if len(st.session_state.history) > 1:
            st.session_state.history.pop()
            st.session_state.data = st.session_state.history[-1].copy()
            st.rerun()

    # Tabela editável
    edited = st.data_editor(st.session_state.data, use_container_width=True, num_rows="dynamic")

    if not edited.equals(st.session_state.data):
        st.session_state.history.append(edited.copy())
        st.session_state.data = edited

    # Exportação
    xlsx = BytesIO()
    with pd.ExcelWriter(xlsx, engine='openpyxl') as writer:
        edited.to_excel(writer, index=False)
    st.download_button("📥 Baixar Planilha Limpa", xlsx.getvalue(), "extrato_limpo.xlsx")

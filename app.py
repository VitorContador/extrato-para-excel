import pdfplumber
import pandas as pd
import re
import streamlit as st
from io import BytesIO

st.set_page_config(page_title="Conversor Profissional - Vitor", layout="wide")

class NubankUltraParser:
    def __init__(self):
        self.date_pattern = re.compile(r'^\d{2}\s[A-Z]{3}')
        # Lista de termos que indicam resumos/cabeçalhos e não devem virar linhas
        self.blacklist = [
            "atendimento", "ouvidoria", "mande uma mensagem", "duvida", "ligue", 
            "gerado dia", "nubank.com.br", "total de entradas", "total de saídas",
            "saldo final", "rendimento líquido", "movimentações", "saldo inicial"
        ]

    def clean_val(self, val_str):
        if not val_str: return 0.0
        # Remove caracteres indesejados mantendo o sinal de menos
        clean = re.sub(r'[^0-9,\.\-]', '', str(val_str))
        if ',' in clean:
            clean = clean.replace('.', '').replace(',', '.')
        try: 
            return round(float(clean), 2)
        except: return 0.0

    def parse(self, pdf_file):
        extracted_rows = []
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                words = page.extract_words(keep_blank_chars=True, y_tolerance=3)
                
                current_tx = None
                last_seen_date = ""
                
                for w in words:
                    text = w['text'].strip()
                    x0 = w['x0']
                    text_lower = text.lower()
                    
                    # Filtro de rodapé e institucional
                    if any(word in text_lower for word in self.blacklist):
                        continue
                    if re.match(r'^\d+\sde\s\d+$', text):
                        continue

                    # 1. Detecta Data
                    if self.date_pattern.match(text):
                        last_seen_date = text
                        if current_tx: extracted_rows.append(current_tx)
                        current_tx = {"Data": last_seen_date, "Historico": "", "Valor_Raw": "", "Pagina": page.page_number}
                    
                    elif current_tx:
                        # 2. Detecta Valor (x0 > 400)
                        if x0 > 400 and (',' in text):
                            # Se for um valor com sinal (+ ou -) vindo sozinho, 
                            # no Nubank isso geralmente indica o TOTAL do grupo. 
                            # Nós queremos apenas os valores individuais (sem o sinal na frente no detalhamento)
                            if (text.startswith('+') or text.startswith('-')) and len(text) > 1:
                                continue 
                            
                            if current_tx["Valor_Raw"] != "":
                                extracted_rows.append(current_tx)
                                current_tx = {"Data": last_seen_date, "Historico": "", "Valor_Raw": text, "Pagina": page.page_number}
                            else:
                                current_tx["Valor_Raw"] = text
                        else:
                            # 3. Acumula Histórico
                            if len(text) > 1:
                                current_tx["Historico"] += f" {text}"
                
                if current_tx: extracted_rows.append(current_tx)
        
        return self.process_to_df(extracted_rows)

    def process_to_df(self, rows):
        df = pd.DataFrame(rows)
        if df.empty: return df
        
        df['Historico'] = df['Historico'].astype(str).str.strip()
        # Remove linhas onde o histórico ficou vazio ou contém termos da blacklist que escaparam
        df = df[df['Historico'].str.len() > 3]
        
        df['Valor_Final'] = df['Valor_Raw'].apply(self.clean_val)
        
        # Lógica de Entrada/Saída: no detalhamento do Nubank, saídas PIX ou Débito 
        # são identificadas pelas palavras no histórico, já que o sinal fica no totalizador.
        def classify(row):
            h = row['Historico'].lower()
            v = row['Valor_Final']
            # Palavras que indicam saída
            if any(x in h for x in ["pagamento", "compra", "enviada", "saída", "débito"]):
                return 0, v
            # Palavras que indicam entrada
            return v, 0

        df[['Entrada', 'Saida']] = df.apply(lambda r: pd.Series(classify(r)), axis=1)
        
        return df[["Data", "Historico", "Entrada", "Saida", "Pagina"]]

# --- Interface ---
st.title("🏦 Conversor de Extratos Profissional")

if 'data' not in st.session_state: st.session_state.data = None
if 'history' not in st.session_state: st.session_state.history = []

file = st.file_uploader("Arraste o extrato aqui", type="pdf")

if file and st.session_state.data is None:
    st.session_state.data = NubankUltraParser().parse(file)
    st.session_state.history.append(st.session_state.data.copy())

if st.session_state.data is not None:
    if st.button("⬅️ Desfazer Alteração"):
        if len(st.session_state.history) > 1:
            st.session_state.history.pop()
            st.session_state.data = st.session_state.history[-1].copy()
            st.rerun()

    edited = st.data_editor(st.session_state.data, use_container_width=True, num_rows="dynamic")

    if not edited.equals(st.session_state.data):
        st.session_state.history.append(edited.copy())
        st.session_state.data = edited

    xlsx = BytesIO()
    with pd.ExcelWriter(xlsx, engine='openpyxl') as writer:
        edited.to_excel(writer, index=False)
    st.download_button("📥 Baixar Planilha Limpa", xlsx.getvalue(), "extrato_limpo.xlsx")

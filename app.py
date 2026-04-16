import pdfplumber
import pandas as pd
import re
import streamlit as st
from io import BytesIO

st.set_page_config(page_title="Conversor Profissional - Vitor", layout="wide")

class NubankDetailParser:
    def __init__(self):
        self.date_pattern = re.compile(r'^\d{2}\s[A-Z]{3}')
        # Palavras que indicam resumo e devem ser ignoradas para evitar duplicidade
        self.summary_keywords = ["total de entradas", "total de saídas", "saldo final", "rendimento líquido"]
        self.blacklist = ["atendimento", "ouvidoria", "mande uma mensagem", "ligue", "gerado dia", "1 de", "2 de"]

    def clean_val(self, val_str):
        if not val_str: return 0.0
        clean = re.sub(r'[^0-9,\.\-]', '', str(val_str))
        if ',' in clean:
            clean = clean.replace('.', '').replace(',', '.')
        try: return round(float(clean), 2)
        except: return 0.0

    def parse(self, pdf_file):
        extracted_rows = []
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                words = page.extract_words(keep_blank_chars=True, y_tolerance=3)
                
                current_tx = None
                last_date = ""

                for w in words:
                    text = w['text'].strip()
                    x0 = w['x0']
                    text_lower = text.lower()

                    # 1. Filtro de Segurança: Ignora rodapés e resumos do dia
                    if any(key in text_lower for key in self.summary_keywords + self.blacklist):
                        continue

                    # 2. Detecta Data ou Novo Lançamento
                    # Se encontrarmos uma data, atualizamos a 'data atual'
                    if self.date_pattern.match(text):
                        last_date = text
                        if current_tx: extracted_rows.append(current_tx)
                        current_tx = {"Data": last_date, "Historico": "", "Valor_Raw": "", "Pagina": page.page_number}
                    
                    elif current_tx:
                        # 3. Detecta Valor Individual (Coluna da direita e com vírgula)
                        # No Nubank, transações individuais não costumam ter o sinal de + na frente, 
                        # enquanto o resumo tem. Isso ajuda a filtrar.
                        if x0 > 400 and (',' in text):
                            # Se já temos um valor para esse histórico, salvamos e abrimos outro (para casos de várias transações sob a mesma data)
                            if current_tx["Valor_Raw"] != "":
                                extracted_rows.append(current_tx)
                                current_tx = {"Data": last_date, "Historico": "", "Valor_Raw": text, "Pagina": page.page_number}
                            else:
                                current_tx["Valor_Raw"] = text
                        else:
                            # 4. Acumula Histórico
                            current_tx["Historico"] += f" {text}"
                
                if current_tx: extracted_rows.append(current_tx)
        
        return self.process_to_df(extracted_rows)

    def process_to_df(self, rows):
        df = pd.DataFrame(rows)
        if df.empty: return df
        
        # Limpeza de campos
        df['Historico'] = df['Historico'].astype(str).str.strip()
        df = df[df['Historico'] != ""] # Remove linhas fantasmas
        
        df['Valor_Final'] = df['Valor_Raw'].apply(self.clean_val)
        
        # No Nubank detalhado, o sinal negativo (-) costuma acompanhar o valor da saída
        df['Entrada'] = df.apply(lambda r: r['Valor_Final'] if '-' not in r['Valor_Raw'] else 0, axis=1)
        df['Saida'] = df.apply(lambda r: abs(r['Valor_Final']) if '-' in r['Valor_Raw'] else 0, axis=1)
        
        return df[["Data", "Historico", "Entrada", "Saida"]]

# --- Interface ---
st.title("🏦 Conversor Nubank (Modo Detalhado)")

if 'data' not in st.session_state: st.session_state.data = None
if 'history' not in st.session_state: st.session_state.history = []

file = st.file_uploader("Suba o extrato para processar os itens individuais", type="pdf")

if file:
    if st.button("🚀 Processar Extrato"):
        st.session_state.data = NubankDetailParser().parse(file)
        st.session_state.history = [st.session_state.data.copy()]

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
    st.download_button("📥 Baixar Excel Detalhado", xlsx.getvalue(), "extrato_detalhado.xlsx")

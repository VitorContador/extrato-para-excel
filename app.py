import pdfplumber
import pandas as pd
import re
import streamlit as st
from io import BytesIO

st.set_page_config(page_title="Conversor Profissional - Vitor", layout="wide")

class NubankUltraParser:
    def __init__(self):
        self.date_pattern = re.compile(r'^\d{2}\s[A-Z]{3}')
        self.blacklist = [
            "atendimento", "ouvidoria", "mande uma mensagem", "duvida", "ligue", 
            "gerado dia", "nubank.com.br", "total de entradas", "total de saídas",
            "saldo final", "rendimento líquido", "movimentações", "saldo inicial"
        ]

    def clean_val(self, val_str):
        if not val_str: return 0.0
        clean = re.sub(r'[^0-9,\.]', '', str(val_str)) # Remove tudo exceto números e pontuação
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
                    
                    if any(word in text_lower for word in self.blacklist): continue
                    if re.match(r'^\d+\sde\s\d+$', text): continue

                    # 1. Detecta Data [cite: 11, 18, 24]
                    if self.date_pattern.match(text):
                        last_seen_date = text
                        if current_tx: extracted_rows.append(current_tx)
                        current_tx = {"Data": last_seen_date, "Historico": "", "Entrada": 0.0, "Saida": 0.0, "Pagina": page.page_number}
                    
                    elif current_tx:
                        # 2. Lógica de Colunas por Coordenada X 
                        # Se o texto tem número e vírgula, verificamos a posição [cite: 12, 16, 20]
                        if ',' in text and any(c.isdigit() for c in text):
                            val = self.clean_val(text)
                            # Se está muito à direita, é o valor da transação [cite: 16, 23, 29]
                            if x0 > 450:
                                # Se o histórico contém palavras de saída, vai para Saída [cite: 31, 32, 57]
                                h_low = current_tx["Historico"].lower()
                                if any(x in h_low for x in ["pagamento", "compra", "enviada", "saída", "débito", "fatura"]):
                                    current_tx["Saida"] = val
                                else:
                                    current_tx["Entrada"] = val
                            continue
                        
                        # 3. Acumula Histórico [cite: 13, 14, 21, 22]
                        if len(text) > 1:
                            current_tx["Historico"] += f" {text}"
                
                if current_tx: extracted_rows.append(current_tx)
        
        return self.process_to_df(extracted_rows)

    def process_to_df(self, rows):
        df = pd.DataFrame(rows)
        if df.empty: return df
        df['Historico'] = df['Historico'].astype(str).str.strip()
        # Filtro para remover linhas de resumo que sobraram 
        df = df[df['Historico'].str.len() > 3]
        return df[["Data", "Historico", "Entrada", "Saida", "Pagina"]]

# --- Interface (Mantida a estrutura aprovada) ---
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

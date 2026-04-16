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
        clean = re.sub(r'[^0-9,\.]', '', str(val_str))
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
                last_y = 0 # Guarda a altura da última captura de valor
                
                for w in words:
                    text = w['text'].strip()
                    x0, y0 = w['x0'], w['top'] # Pega posição horizontal e vertical
                    text_lower = text.lower()
                    
                    if any(word in text_lower for word in self.blacklist): continue
                    if re.match(r'^\d+\sde\s\d+$', text): continue

                    # 1. Detecta Data
                    if self.date_pattern.match(text):
                        last_seen_date = text
                        if current_tx: extracted_rows.append(current_tx)
                        current_tx = {"Data": last_seen_date, "Historico": "", "Entrada": 0.0, "Saida": 0.0, "Pagina": page.page_number}
                        last_y = 0
                    
                    elif current_tx:
                        # 2. Detecta Valor (Coluna Direita)
                        if ',' in text and any(c.isdigit() for c in text) and x0 > 400:
                            # CORREÇÃO CRUCIAL: Só aceita se for uma nova linha vertical (y0 diferente de last_y)
                            if abs(y0 - last_y) > 5: 
                                val = self.clean_val(text)
                                
                                # Se a transação já tem valor e mudou a altura, abre uma nova
                                if (current_tx["Entrada"] > 0 or current_tx["Saida"] > 0):
                                    extracted_rows.append(current_tx)
                                    current_tx = {"Data": last_seen_date, "Historico": "", "Entrada": 0.0, "Saida": 0.0, "Pagina": page.page_number}
                                
                                # Classifica
                                h_low = current_tx["Historico"].lower()
                                if any(x in h_low for x in ["pagamento", "compra", "enviada", "saída", "débito", "fatura"]):
                                    current_tx["Saida"] = val
                                else:
                                    current_tx["Entrada"] = val
                                
                                last_y = y0 # Registra a altura onde o valor foi encontrado
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
        df = df[df['Historico'].str.len() > 2]
        # Limpeza final de duplicatas residuais
        df = df.drop_duplicates(subset=['Data', 'Historico', 'Entrada', 'Saida'])
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

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
        try: return round(float(clean), 2)
        except: return 0.0

    def parse(self, pdf_file):
        extracted_rows = []
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                # O segredo: Extrair palavras agrupadas por linha (Y)
                words = page.extract_words(keep_blank_chars=True, y_tolerance=3)
                
                # Agrupamos as palavras que estão na mesma altura (top)
                lines = {}
                for w in words:
                    y = round(w['top'], 0)
                    if y not in lines: lines[y] = []
                    lines[y].append(w)
                
                last_seen_date = ""
                
                # Processamos linha por linha da página
                for y in sorted(lines.keys()):
                    line_words = sorted(lines[y], key=lambda x: x['x0'])
                    line_text = " ".join([w['text'] for w in line_words]).strip()
                    line_text_lower = line_text.lower()
                    
                    # Filtros de segurança
                    if any(word in line_text_lower for word in self.blacklist): continue
                    if (line_text.startswith('+') or line_text.startswith('-')) and any(c.isdigit() for c in line_text): continue
                    if re.match(r'^\d+\sde\s\d+$', line_text): continue

                    # 1. Se a linha tem data, atualizamos a data de referência
                    date_match = self.date_pattern.match(line_text)
                    if date_match:
                        last_seen_date = date_match.group()
                    
                    # 2. Identifica se a linha tem um valor na direita (Coluna de Valor)
                    val_text = ""
                    hist_text = ""
                    
                    for w in line_words:
                        if w['x0'] > 400 and ',' in w['text'] and any(c.isdigit() for c in w['text']):
                            val_text = w['text']
                        else:
                            # Evita repetir a data no histórico
                            t = w['text']
                            if not self.date_pattern.match(t):
                                hist_text += f" {t}"
                    
                    # 3. Se achamos um valor, criamos o lançamento com o histórico daquela MESMA linha
                    if val_text and last_seen_date:
                        val_num = self.clean_val(val_text)
                        h_low = hist_text.lower()
                        
                        entrada, saida = 0.0, 0.0
                        if any(x in h_low for x in ["pagamento", "compra", "enviada", "saída", "débito", "fatura", "enviado"]):
                            saida = val_num
                        else:
                            entrada = val_num
                            
                        extracted_rows.append({
                            "Data": last_seen_date,
                            "Historico": hist_text.strip(),
                            "Entrada": entrada,
                            "Saida": saida,
                            "Pagina": page.page_number
                        })
        
        return self.process_to_df(extracted_rows)

    def process_to_df(self, rows):
        df = pd.DataFrame(rows)
        if df.empty: return df
        # Limpa históricos que ficaram apenas com "Total" ou sujeira
        df = df[df['Historico'].str.len() > 3]
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

import pdfplumber
import pandas as pd
import re
import streamlit as st
from io import BytesIO

st.set_page_config(page_title="Conversor Contábil PRO", layout="wide")

class NubankProParser:
    def __init__(self):
        self.date_pattern = re.compile(r'^\d{2}\s[A-Z]{3}')
        
        self.blacklist = [
            "atendimento", "ouvidoria", "mande uma mensagem", "duvida", "ligue", 
            "gerado dia", "nubank.com.br", "total de entradas", "total de saídas",
            "saldo final", "rendimento líquido", "movimentações", "saldo inicial",
            "valores em r$"
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
        # CORREÇÃO 1: A memória da data agora fica FORA do loop de páginas.
        # Assim ele não "esquece" o dia quando o PDF pula para a página 2.
        current_date = "" 
        
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                words = page.extract_words(keep_blank_chars=True, y_tolerance=3)
                temp_history = ""
                
                for w in words:
                    text = w['text'].strip()
                    x0 = w['x0']
                    text_lower = text.lower()
                    
                    if (text.startswith('+') or text.startswith('-')) and any(c.isdigit() for c in text):
                        continue
                    if any(word in text_lower for word in self.blacklist):
                        continue
                    if re.match(r'^\d+\sde\s\d+$', text):
                        continue

                    if self.date_pattern.match(text):
                        current_date = text
                        continue

                    # Ampliei a margem (x0 > 350) para garantir que pega valores maiores
                    if x0 > 350 and ',' in text and any(c.isdigit() for c in text):
                        val_num = self.clean_val(text)
                        
                        if current_date and temp_history:
                            h_low = temp_history.lower()
                            entrada, saida = 0.0, 0.0
                            
                            if any(x in h_low for x in ["pagamento", "compra", "enviada", "débito", "fatura", "saída", "saida", "aplicação", "aplicacao"]):
                                saida = val_num
                            else:
                                entrada = val_num
                                
                            extracted_rows.append({
                                "Data": current_date,
                                "Historico": temp_history.strip(),
                                "Entrada": entrada,
                                "Saida": saida,
                                "Pagina": page.page_number
                            })
                            temp_history = ""
                        continue

                    if len(text) > 1 and not text.isdigit():
                        temp_history += f" {text}"
                
        return self.process_to_df(extracted_rows)

    def process_to_df(self, rows):
        df = pd.DataFrame(rows)
        if df.empty: return df
        
        df['Historico'] = df['Historico'].astype(str)
        df['Historico'] = df['Historico'].str.split(r'\s*-\s*\*\*\*').str[0]
        df['Historico'] = df['Historico'].str.split(r'\s*-\s*NU PAGAMENTOS|\s*-\s*BCO DO BRASIL|\s*-\s*ITAÚ UNIBANCO|\s*-\s*BANCO INTER').str[0]
        df['Historico'] = df['Historico'].str.strip()
        
        df = df[df['Historico'].str.len() > 3]
        if not df.empty:
            df = df.drop_duplicates(subset=['Data', 'Historico', 'Entrada', 'Saida'])
            return df[["Data", "Historico", "Entrada", "Saida", "Pagina"]]
        return df

# --- Interface Automática e Anti-Bug ---
st.title("🏦 Conversor de Extratos PRO")

# CORREÇÃO 2: Gerenciamento de Sessão super rígido para evitar o "Empty State"
if 'data' not in st.session_state: st.session_state.data = None
if 'history' not in st.session_state: st.session_state.history = []
if 'last_filename' not in st.session_state: st.session_state.last_filename = ""

file = st.file_uploader("Arraste o extrato aqui", type="pdf")

# Mágica do Streamlit: Se o usuário apagar o arquivo no "X", a memória é apagada junto
if file is None:
    st.session_state.data = None
    st.session_state.history = []
    st.session_state.last_filename = ""
else:
    # Se o arquivo for diferente do que estava travado na memória, ele reseta forçadamente
    if file.name != st.session_state.last_filename:
        st.session_state.data = None
        st.session_state.history = []
        st.session_state.last_filename = file.name

    if st.session_state.data is None:
        with st.spinner("Processando com Inteligência PRO..."):
            st.session_state.data = NubankProParser().parse(file)
            st.session_state.history = [st.session_state.data.copy()]

if st.session_state.data is not None and not st.session_state.data.empty:
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
    st.download_button("📥 Baixar Planilha Limpa (Excel)", xlsx.getvalue(), "extrato_contabil.xlsx")
elif st.session_state.data is not None and st.session_state.data.empty:
    st.error("Não encontramos lançamentos válidos. Verifique se é um extrato do Nubank no formato padrão.")

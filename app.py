import pdfplumber
import pandas as pd
import re
import streamlit as st
from io import BytesIO

st.set_page_config(page_title="Conversor Contábil PRO", layout="wide")

# ==========================================
# 1. PARSER NUBANK (CORRIGIDO E BLINDADO)
# ==========================================
class NubankProParser:
    def __init__(self):
        # Regex flexível para datas: "02 OUT" ou "02 OUT 2025"
        self.date_pattern = re.compile(r'\d{2}\s[A-Z]{3}')
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
        # Mantém a data viva entre as páginas
        current_date = "" 
        
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                words = page.extract_words(keep_blank_chars=True, y_tolerance=3)
                temp_history = ""
                
                for w in words:
                    text = w['text'].strip()
                    x0 = w['x0']
                    text_lower = text.lower()
                    
                    # Ignora totais com sinal (+48,50 ou -414,48)
                    if (text.startswith('+') or text.startswith('-')) and any(c.isdigit() for c in text):
                        continue
                    if any(word in text_lower for word in self.blacklist):
                        continue
                    if re.match(r'^\d+\sde\s\d+$', text):
                        continue

                    # Captura a data mesmo se estiver no meio de outro texto
                    date_search = self.date_pattern.search(text)
                    if date_search:
                        current_date = date_search.group()
                        continue

                    # Identifica valor na coluna da direita
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
        
        # Limpeza do histórico (tira CPFs e nomes de bancos)
        df['Historico'] = df['Historico'].astype(str)
        df['Historico'] = df['Historico'].str.split(r'\s*-\s*\*\*\*').str[0]
        df['Historico'] = df['Historico'].str.split(r'\s*-\s*NU PAGAMENTOS|\s*-\s*BCO DO BRASIL|\s*-\s*ITAÚ UNIBANCO|\s*-\s*BANCO INTER').str[0]
        df['Historico'] = df['Historico'].str.strip()
        
        df = df[df['Historico'].str.len() > 3]
        if not df.empty:
            df = df.drop_duplicates(subset=['Data', 'Historico', 'Entrada', 'Saida'])
            return df[["Data", "Historico", "Entrada", "Saida", "Pagina"]]
        return df

# ==========================================
# 2. PARSER BANCO INTER (MANTIDO IGUAL)
# ==========================================
class InterParser:
    def __init__(self):
        self.date_pattern = re.compile(r'\d{1,2}\sde\s[A-Za-zçÇ]+\sde\s\d{4}')
        self.blacklist = ["saldo total", "saldo disponivel", "saldo bloqueado", "solicitado em", "período:"]

    def clean_val(self, val_str):
        if not val_str: return 0.0
        clean = re.sub(r'[^0-9,\.]', '', str(val_str))
        if ',' in clean: clean = clean.replace('.', '').replace(',', '.')
        try: return round(float(clean), 2)
        except: return 0.0

    def parse(self, pdf_file):
        extracted_rows = []
        current_date = ""
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                words = page.extract_words(keep_blank_chars=True)
                lines = {}
                for w in words:
                    y = round(w['top'], 1)
                    found = False
                    for ey in lines.keys():
                        if abs(y - ey) < 4: lines[ey].append(w); found = True; break
                    if not found: lines[y] = [w]
                
                for y in sorted(lines.keys()):
                    line_words = sorted(lines[y], key=lambda x: x['x0'])
                    line_text = " ".join([w['text'] for w in line_words]).strip()
                    if self.date_pattern.search(line_text) and "saldo do dia" in line_text.lower():
                        current_date = self.date_pattern.search(line_text).group(0)
                        continue
                    curr_matches = re.findall(r'-?R\$\s*[\d\.,]+', line_text)
                    if curr_matches and current_date:
                        v_str = curr_matches[0]
                        v_num = self.clean_val(v_str)
                        hist = line_text[:line_text.find(v_str)].strip().replace('"', '')
                        ent, sai = (0.0, v_num) if v_str.startswith('-') else (v_num, 0.0)
                        if hist:
                            extracted_rows.append({"Data": current_date, "Historico": hist, "Entrada": ent, "Saida": sai, "Pagina": page.page_number})
        return self.process_to_df(extracted_rows)

    def process_to_df(self, rows):
        df = pd.DataFrame(rows)
        if df.empty: return df
        df['Historico'] = df['Historico'].str.replace(r'Cp\s*:\s*\d+-', '', regex=True)
        return df[["Data", "Historico", "Entrada", "Saida", "Pagina"]]

# ==========================================
# 3. IDENTIFICADOR DE BANCO (MELHORADO)
# ==========================================
def identificar_banco(pdf_file):
    try:
        with pdfplumber.open(pdf_file) as pdf:
            texto = pdf.pages[0].extract_text().lower()
            # O Nubank agora é identificado por termos que SEMPRE aparecem na primeira página
            if any(x in texto for x in ["nu pagamentos", "30.680.829/0001-43", "saldo final do período", "movimentações"]):
                return "Nubank"
            elif "banco inter" in texto:
                return "Banco Inter"
    except: pass
    return "Desconhecido"

# ==========================================
# 4. INTERFACE STREAMLIT
# ==========================================
st.title("🏦 Conversor de Extratos PRO")

if 'data' not in st.session_state: st.session_state.data = None
if 'history' not in st.session_state: st.session_state.history = []
if 'last_filename' not in st.session_state: st.session_state.last_filename = ""

file = st.file_uploader("Arraste o PDF (Nubank ou Inter)", type="pdf")

if file is None:
    st.session_state.data = None
    st.session_state.last_filename = ""
else:
    if file.name != st.session_state.last_filename:
        st.session_state.data = None
        st.session_state.last_filename = file.name

    if st.session_state.data is None:
        with st.spinner("Identificando Banco..."):
            banco = identificar_banco(file)
            if banco == "Nubank": parser = NubankProParser()
            elif banco == "Banco Inter": parser = InterParser()
            else:
                st.error("⚠️ Banco não reconhecido.")
                st.stop()
            st.session_state.data = parser.parse(file)
            st.session_state.history = [st.session_state.data.copy()]

if st.session_state.data is not None and not st.session_state.data.empty:
    st.success(f"✅ Extrato: **{identificar_banco(file)}**")
    if st.button("⬅️ Desfazer"):
        if len(st.session_state.history) > 1:
            st.session_state.history.pop()
            st.session_state.data = st.session_state.history[-1].copy()
            st.rerun()
    edited = st.data_editor(st.session_state.data, use_container_width=True, num_rows="dynamic")
    xlsx = BytesIO()
    with pd.ExcelWriter(xlsx, engine='openpyxl') as writer: edited.to_excel(writer, index=False)
    st.download_button("📥 Baixar Excel", xlsx.getvalue(), "extrato.xlsx")

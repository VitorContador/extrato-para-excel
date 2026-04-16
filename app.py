import pdfplumber
import pandas as pd
import re
import streamlit as st
from io import BytesIO

st.set_page_config(page_title="Conversor Contábil PRO", layout="wide")

# ==========================================
# 1. PARSER NUBANK (INTOCADO - VERSÃO PRO)
# ==========================================
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


# ==========================================
# 2. NOVO: PARSER BANCO INTER
# ==========================================
class InterParser:
    def __init__(self):
        # Regex para datas do Inter: "10 de Março de 2026"
        self.date_pattern = re.compile(r'\d{1,2}\sde\s[A-Za-zçÇ]+\sde\s\d{4}')
        self.blacklist = [
            "saldo total", "saldo disponivel", "saldo bloqueado", 
            "bloqueado + disponivel", "valor", "saldo por transação", 
            "solicitado em", "fale com a gente", "sac:", "ouvidoria:", 
            "deficiência de fala", "período:", "cpf/cnpj:", "instituição: banco inter"
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
        current_date = ""
        
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                words = page.extract_words(keep_blank_chars=True)
                
                # Agrupamento milimétrico por linha (Y-axis)
                lines = {}
                for w in words:
                    y = round(w['top'], 1)
                    found = False
                    for existing_y in lines.keys():
                        if abs(y - existing_y) < 4: # Tolerância de 4 pixels na mesma linha
                            lines[existing_y].append(w)
                            found = True
                            break
                    if not found:
                        lines[y] = [w]
                
                # Lendo o texto linha por linha de cima para baixo
                for y in sorted(lines.keys()):
                    line_words = sorted(lines[y], key=lambda x: x['x0'])
                    line_text = " ".join([w['text'] for w in line_words]).strip()
                    line_text_lower = line_text.lower()
                    
                    # Filtra cabeçalhos e rodapés do Inter
                    if any(word in line_text_lower for word in self.blacklist):
                        continue
                        
                    # 1. Verifica se a linha contém a Data ("10 de Março de 2026 Saldo do dia...")
                    date_match = self.date_pattern.search(line_text)
                    if date_match and "saldo do dia" in line_text_lower:
                        current_date = date_match.group(0)
                        continue # Pula o resto da linha pois é só cabeçalho de dia
                        
                    # 2. Busca valores financeiros na linha (ex: -R$ 417,26 ou R$ 140,00)
                    currency_matches = re.findall(r'-?R\$\s*[\d\.,]+', line_text)
                    
                    if currency_matches and current_date:
                        # O Inter tem 2 valores na linha (Transação e Saldo). Queremos só o primeiro!
                        val_str = currency_matches[0]
                        val_num = self.clean_val(val_str)
                        
                        # O histórico é tudo que está escrito ANTES do primeiro R$
                        history = line_text[:line_text.find(val_str)].strip()
                        
                        entrada, saida = 0.0, 0.0
                        if val_str.startswith('-'):
                            saida = val_num
                        else:
                            entrada = val_num
                            
                        # Limpeza do histórico (Tira aspas que o Inter coloca)
                        history = history.replace('"', '').strip()
                            
                        if history:
                            extracted_rows.append({
                                "Data": current_date,
                                "Historico": history,
                                "Entrada": entrada,
                                "Saida": saida,
                                "Pagina": page.page_number
                            })
                            
        return self.process_to_df(extracted_rows)

    def process_to_df(self, rows):
        df = pd.DataFrame(rows)
        if df.empty: return df
        df['Historico'] = df['Historico'].astype(str)
        
        # Limpeza Premium do Inter: Remove o "Cp:XXXXXXXX-" que vem nos Pix
        df['Historico'] = df['Historico'].str.replace(r'Cp:\d+-', '', regex=True)
        
        df = df.drop_duplicates(subset=['Data', 'Historico', 'Entrada', 'Saida'])
        return df[["Data", "Historico", "Entrada", "Saida", "Pagina"]]


# ==========================================
# 3. IDENTIFICADOR AUTOMÁTICO DE BANCO
# ==========================================
def identificar_banco(pdf_file):
    try:
        with pdfplumber.open(pdf_file) as pdf:
            primeira_pagina = pdf.pages[0].extract_text().lower()
            # Procura por CNPJ ou nome do Nubank
            if "nu pagamentos" in primeira_pagina or "30.680.829/0001-43" in primeira_pagina:
                return "Nubank"
            # Procura pelo nome do Inter
            elif "banco inter" in primeira_pagina:
                return "Banco Inter"
    except Exception as e:
        pass
    return "Desconhecido"


# ==========================================
# 4. INTERFACE E LÓGICA DO STREAMLIT
# ==========================================
st.title("🏦 Conversor de Extratos Multibancos PRO")

# Memória persistente
if 'data' not in st.session_state: st.session_state.data = None
if 'history' not in st.session_state: st.session_state.history = []
if 'last_filename' not in st.session_state: st.session_state.last_filename = ""
if 'banco_detectado' not in st.session_state: st.session_state.banco_detectado = ""

file = st.file_uploader("Arraste o extrato em PDF aqui (Nubank ou Inter)", type="pdf")

if file is None:
    st.session_state.data = None
    st.session_state.history = []
    st.session_state.last_filename = ""
    st.session_state.banco_detectado = ""
else:
    if file.name != st.session_state.last_filename:
        st.session_state.data = None
        st.session_state.history = []
        st.session_state.last_filename = file.name
        st.session_state.banco_detectado = ""

    if st.session_state.data is None:
        with st.spinner("Analisando PDF e identificando o Banco..."):
            
            # Passo 1: Descobre qual é o banco
            banco = identificar_banco(file)
            st.session_state.banco_detectado = banco
            
            # Passo 2: Direciona para o robô correto
            if banco == "Nubank":
                parser = NubankProParser()
            elif banco == "Banco Inter":
                parser = InterParser()
            else:
                st.error("⚠️ Banco não reconhecido. Certifique-se que é um PDF digital do Nubank ou Banco Inter.")
                st.stop()
                
            # Passo 3: Processa os dados
            st.session_state.data = parser.parse(file)
            st.session_state.history = [st.session_state.data.copy()]

# Renderiza Tabela
if st.session_state.data is not None and not st.session_state.data.empty:
    st.success(f"✅ Extrato identificado e processado: **{st.session_state.banco_detectado}**")
    
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
    st.warning(f"O banco foi identificado como **{st.session_state.banco_detectado}**, mas não encontramos transações válidas na leitura.")

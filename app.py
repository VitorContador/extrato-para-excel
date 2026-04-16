import pdfplumber
import pandas as pd
import re
import streamlit as st
from io import BytesIO

st.set_page_config(page_title="Conversor Contábil PRO", layout="wide")

class NubankProParser:
    def __init__(self):
        # Padrão de datas do Nubank (ex: 02 OUT 2025)
        self.date_pattern = re.compile(r'^\d{2}\s[A-Z]{3}')
        
        # Ignora lixo de cabeçalho, rodapé e totais que bugam a leitura
        self.blacklist = [
            "atendimento", "ouvidoria", "mande uma mensagem", "duvida", "ligue", 
            "gerado dia", "nubank.com.br", "total de entradas", "total de saídas",
            "saldo final", "rendimento líquido", "movimentações", "saldo inicial",
            "valores em r$"
        ]

    def clean_val(self, val_str):
        if not val_str: return 0.0
        # Mantém apenas números e pontuação
        clean = re.sub(r'[^0-9,\.]', '', str(val_str))
        if ',' in clean:
            clean = clean.replace('.', '').replace(',', '.')
        try: return round(float(clean), 2)
        except: return 0.0

    def parse(self, pdf_file):
        extracted_rows = []
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                words = page.extract_words(keep_blank_chars=True, y_tolerance=3)
                
                current_date = ""
                temp_history = ""
                
                for w in words:
                    text = w['text'].strip()
                    x0 = w['x0']
                    text_lower = text.lower()
                    
                    # 1. BLOQUEIOS DE SEGURANÇA (Mata totais e rodapé)
                    if (text.startswith('+') or text.startswith('-')) and any(c.isdigit() for c in text):
                        continue
                    if any(word in text_lower for word in self.blacklist):
                        continue
                    if re.match(r'^\d+\sde\s\d+$', text):
                        continue

                    # 2. CAPTURA A DATA
                    if self.date_pattern.match(text):
                        current_date = text
                        continue

                    # 3. CAPTURA O VALOR E FINALIZA O LANÇAMENTO
                    # Se achou um número com vírgula na coluna da direita
                    if x0 > 400 and ',' in text and any(c.isdigit() for c in text):
                        val_num = self.clean_val(text)
                        
                        # Se temos um histórico acumulado, fechamos o lançamento
                        if current_date and temp_history:
                            h_low = temp_history.lower()
                            entrada, saida = 0.0, 0.0
                            
                            # Palavras que jogam o valor OBRIGATORIAMENTE para SAÍDA
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
                            # Limpa a sacola de histórico para o próximo item do dia
                            temp_history = ""
                        continue

                    # 4. ACUMULA O HISTÓRICO DA TRANSAÇÃO
                    # Ignora números isolados que não são valor
                    if len(text) > 1 and not text.isdigit():
                        temp_history += f" {text}"
                
        return self.process_to_df(extracted_rows)

    def process_to_df(self, rows):
        df = pd.DataFrame(rows)
        if df.empty: return df
        
        # --- LIMPEZA PREMIUM DO HISTÓRICO ---
        # Corta o texto a partir do CPF mascarado (ex: - ***.549...)
        df['Historico'] = df['Historico'].str.split(r'\s*-\s*\*\*\*').str[0]
        # Corta a partir de nomes de bancos caso não tenha CPF
        df['Historico'] = df['Historico'].str.split(r'\s*-\s*NU PAGAMENTOS|\s*-\s*BCO DO BRASIL|\s*-\s*ITAÚ UNIBANCO|\s*-\s*BANCO INTER').str[0]
        
        df['Historico'] = df['Historico'].astype(str).str.strip()
        
        # Remove eventuais linhas fantasmas e duplicatas
        df = df[df['Historico'].str.len() > 3]
        df = df.drop_duplicates(subset=['Data', 'Historico', 'Entrada', 'Saida'])
        
        return df[["Data", "Historico", "Entrada", "Saida", "Pagina"]]

# --- Interface Automática ---
st.title("🏦 Conversor de Extratos PRO")

if 'data' not in st.session_state: st.session_state.data = None
if 'history' not in st.session_state: st.session_state.history = []

file = st.file_uploader("Arraste o extrato aqui", type="pdf")

if file and st.session_state.data is None:
    with st.spinner("Processando com Inteligência PRO..."):
        st.session_state.data = NubankProParser().parse(file)
        st.session_state.history = [st.session_state.data.copy()]

if st.session_state.data is not None:
    if st.button("⬅️ Desfazer Alteração"):
        if len(st.session_state.history) > 1:
            st.session_state.history.pop()
            st.session_state.data = st.session_state.history[-1].copy()
            st.rerun()

    # Planilha na tela
    edited = st.data_editor(st.session_state.data, use_container_width=True, num_rows="dynamic")

    if not edited.equals(st.session_state.data):
        st.session_state.history.append(edited.copy())
        st.session_state.data = edited

    # Exportação
    xlsx = BytesIO()
    with pd.ExcelWriter(xlsx, engine='openpyxl') as writer:
        edited.to_excel(writer, index=False)
    st.download_button("📥 Baixar Planilha Limpa (Excel)", xlsx.getvalue(), "extrato_contabil.xlsx")

import streamlit as st
import pdfplumber
import openpyxl
import subprocess
import os
import re
import datetime
from io import BytesIO
from bs4 import BeautifulSoup
from paises import PAISES

st.set_page_config(page_title="DJIM / DJIM Electrónica", page_icon="📄", layout="centered")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
.djim-header {
    background: linear-gradient(135deg, #1e2440 0%, #2a3060 100%);
    border-radius: 12px; padding: 1.8rem 2.5rem; margin-bottom: 1.5rem;
    border-left: 5px solid #4f8ef7;
}
.djim-header h1 { color: #fff; font-size: 1.7rem; font-weight: 600; margin: 0 0 0.3rem 0; }
.djim-header p { color: #7b8db0; font-size: 0.85rem; margin: 0; font-family: 'IBM Plex Mono', monospace; }
.section-title {
    font-size: 0.7rem; font-weight: 600; letter-spacing: 2px;
    text-transform: uppercase; color: #4f8ef7;
    margin: 2rem 0 0.8rem 0; padding-bottom: 0.5rem; border-bottom: 1px solid #e0e8f0;
}
.alerta-ok {
    background: #e8f5e9; border: 1px solid #a5d6a7; border-radius: 8px;
    padding: 0.8rem 1.2rem; color: #2e7d32; font-weight: 500; font-size: 0.9rem; margin: 0.5rem 0;
}
[data-testid="stToolbar"] { visibility: hidden !important; }
[data-testid="stDecoration"] { display: none !important; }
[data-testid="stHeader"] { display: none !important; }
#GithubIcon { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="djim-header">
    <h1>📄 DJIM / DJIM Electrónica</h1>
    <p>Generador automático · Interlog Grupo 8</p>
</div>
""", unsafe_allow_html=True)

TEMPLATE_PATH = "template_djim.xlsx"

if "n_items" not in st.session_state:
    st.session_state.n_items = 0

# ─── UTILIDADES PDF ───

def extract_text_pdfplumber(pdf_bytes):
    text = ""
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
    except:
        pass
    return text.strip()


def ocr_pdf_bytes(pdf_bytes, label, dpi=250, psm=None, upscale=1):
    """
    psm: si se especifica, fuerza el modo de segmentación de página de tesseract
         (6 = asume un único bloque uniforme de texto; mejor para tablas chicas
         tipo capturas de pantalla, donde el psm automático reordena columnas).
    upscale: factor de reescalado de la imagen antes de pasarla a tesseract.
             Útil cuando la imagen fuente es de baja resolución (ej: DNRPA
             que son capturas de pantalla), ya que tesseract reconoce mejor
             dígitos y letras chicas en imágenes más grandes.
    """
    tmp_pdf = f"/tmp/{label}.pdf"
    with open(tmp_pdf, "wb") as f:
        f.write(pdf_bytes)
    subprocess.run(["pdftoppm", "-r", str(dpi), tmp_pdf, f"/tmp/ocr_{label}"], capture_output=True)
    images = sorted([x for x in os.listdir("/tmp") if x.startswith(f"ocr_{label}")])
    text = ""
    for img in images:
        img_path = f"/tmp/{img}"
        if upscale and upscale > 1:
            try:
                from PIL import Image, ImageOps
                im = Image.open(img_path).convert("L")
                im = im.resize((im.width * upscale, im.height * upscale), Image.LANCZOS)
                im = ImageOps.autocontrast(im)
                im.save(img_path)
            except Exception:
                pass
        cmd = ["tesseract", img_path, "stdout"]
        if psm:
            cmd += ["--psm", str(psm)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        text += result.stdout
    for img in images:
        try: os.remove(f"/tmp/{img}")
        except: pass
    return text


def get_text(pdf_bytes, label, dpi=250, psm=None, upscale=1):
    text = extract_text_pdfplumber(pdf_bytes)
    chars_utiles = len(re.findall(r'[A-Za-z0-9]', text))
    if not text or chars_utiles < 30:
        text = ocr_pdf_bytes(pdf_bytes, label, dpi=dpi, psm=psm, upscale=upscale)
    return text

def get_text_di(pdf_bytes, label, dpi=250):
    """Para DI: pdfplumber primero, OCR si no tiene CUIT ni fecha."""
    text = extract_text_pdfplumber(pdf_bytes)
    tiene_cuit = bool(re.search(r'\d{2}-\d{8}-\d', text))
    tiene_fecha = bool(re.search(r'\d{2}/\d{2}/\d{4}', text))
    if not tiene_cuit or not tiene_fecha:
        text = ocr_pdf_bytes(pdf_bytes, label, dpi=dpi)
    return text


def normalizar_ocr(text):
    """Corrige errores comunes de OCR antes del parseo."""
    # 1C04 o 1CO4 → IC04 (I confundida con 1, O confundida con 0)
    text = re.sub(r'(?<!\d)1([CG])[O0](\d)', r'IC0\2', text, flags=re.IGNORECASE)
    text = re.sub(r'(?<!\d)1([CG])(\d)', r'I\1\2', text, flags=re.IGNORECASE)
    # ICO4 → IC04
    text = re.sub(r'IC[Oo](\d)', r'IC0\1', text)
    text = re.sub(r'IG[Oo](\d)', r'IG0\1', text)
    # O73 → 073 (O al inicio de número de aduana)
    text = re.sub(r'\bO(\d{2})\b', r'0\1', text)
    return text


# ─── PARSEO DI ───

def parsear_nro_despacho(text_upper):
    m = re.search(r'(\d{2})\s+(\d{3})\s+((?:IC|IG)\d{2})\s+(\d+)\s+([A-Z])(?:\s|$|[^A-Z0-9])', text_upper)
    if m:
        return m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
    m = re.search(r'(\d{2})\s+(\d{3})\s+([CG]\d{2})\s+(\d+)\s+([A-Z])(?:\s|$|[^A-Z0-9])', text_upper)
    if m:
        return m.group(1), m.group(2), 'I' + m.group(3), m.group(4), m.group(5)
    m = re.search(r'\*(\d{2})(\d{3})(IC\d{2}|IG\d{2})(\d+)([A-Z])\*', text_upper)
    if m:
        return m.groups()
    return None


_STOPWORDS_PAIS = frozenset({'DE', 'DEL', 'LA', 'EL', 'LOS', 'LAS', 'Y'})


def _palabras_significativas_pais(nombre):
    limpio = re.sub(r'[^A-ZÑÁÉÍÓÚ]+', ' ', nombre.upper())
    return [p for p in limpio.split() if p and p not in _STOPWORDS_PAIS]


def extraer_codigos_pais(texto, PAISES, slack=2):
    """
    Busca nombres de país dentro de un fragmento de texto y devuelve una
    lista (posición, código) ordenada por posición de aparición.

    FIX (orden y puntuación): el nombre del país tal como aparece impreso
    en el DI no siempre coincide textualmente con la clave de la tabla
    (ej: el DI imprime "REP. FED DE ALEMANIA" pero la tabla tiene la
    clave "ALEMANIA,REP.FED." — mismas palabras, orden y puntuación
    distintos). Por eso NO se busca la clave tal cual como substring:
    se comparan las palabras significativas de cada clave (ignorando
    conectores como "DE") contra los tokens del texto, toleradas hasta
    `slack` palabras sueltas intercaladas (ej: el "DE" del medio).

    FIX (límite de palabra): al comparar por TOKENS completos (no
    substrings), un país corto como "ARGENTINA" ya no puede matchear
    dentro de una palabra más larga no relacionada como
    "BANCOSARGENTINA" (un campo interno de opciones del DI) — antes sí
    pasaba, y hacía que el país saliera completamente mal cuando el
    nombre real no coincidía con ninguna clave (ver arriba) y la
    búsqueda caía en ese falso positivo.

    Cuando el mismo país aparece dos veces seguidas (lo normal: una vez
    para "Origen País" y otra para "Procedencia"), cada aparición se
    detecta por separado — el algoritmo corta la búsqueda de una
    ocurrencia en cuanto encontraría una palabra ya usada por esa misma
    ocurrencia, en vez de seguir de largo y devorar el comienzo de la
    segunda aparición.
    """
    tokens = [(mm.group(0), mm.start()) for mm in re.finditer(r'[A-ZÑÁÉÍÓÚ]+', texto)]
    n = len(tokens)
    usados_tok = [False] * n
    encontrados = []

    claves = [(_palabras_significativas_pais(pais), codigo) for pais, codigo in PAISES.items()]
    claves = [(p, c) for p, c in claves if p]
    claves.sort(key=lambda t: -len(t[0]))  # nombres más específicos (más palabras) primero

    for palabras, codigo in claves:
        pset = set(palabras)
        i = 0
        while i < n:
            if usados_tok[i] or tokens[i][0] not in pset:
                i += 1
                continue
            faltan = set(pset)
            grupo = []
            fillers = 0
            j = i
            while j < n and faltan:
                if usados_tok[j]:
                    break
                palabra = tokens[j][0]
                if palabra in faltan:
                    faltan.discard(palabra)
                    grupo.append(j)
                    j += 1
                elif palabra in pset:
                    break  # palabra repetida: es el comienzo de OTRA aparición
                else:
                    fillers += 1
                    if fillers > slack:
                        break
                    j += 1
            if not faltan:
                for k in grupo:
                    usados_tok[k] = True
                encontrados.append((tokens[i][1], codigo))
                i = grupo[-1] + 1
            else:
                i += 1

    encontrados.sort(key=lambda x: x[0])
    return encontrados


def parsear_di(text):
    from paises import PAISES
    datos = {}
    alertas = []

    # Normalizar errores de OCR ANTES de procesar
    text_norm = normalizar_ocr(text)
    text_norm_upper = text_norm.upper()

    # Este diccionario ahora se usa SOLO como fallback (ver más abajo), cuando
    # no se pudo parsear el número de despacho. El código numérico de aduana
    # que viene directamente del número de despacho es siempre más confiable
    # que buscar el nombre de la aduana en todo el texto del DI (el nombre
    # puede aparecer también en otras secciones, como la tabla de Ingresos
    # Brutos por jurisdicción, y generar falsos positivos).
    ADUANAS = {
        'BS.AS. (CAPITAL)': '001', 'BS.AS.(CAPITAL)': '001', 'BUENOS AIRES CAPITAL': '001',
        'BAHIA BLANCA': '003', 'BARILOCHE': '004', 'CAMPANA': '008',
        'BARRANQUERAS': '010', 'CLORINDA': '012', 'COLON': '013',
        'COMODORO RIVADAVIA': '014', 'CONCEPCION DEL URUGUAY': '015',
        'CONCORDIA': '016', 'CORDOBA': '017', 'CORRIENTES': '018',
        'PUERTO DESEADO': '019', 'DIAMANTE': '020', 'ESQUEL': '023',
        'FORMOSA': '024', 'GOYA': '025', 'GUALEGUAYCHU': '026',
        'IGUAZU': '029', 'JUJUY': '031', 'LA PLATA': '033',
        'LA QUIACA': '034', 'MAR DEL PLATA': '037', 'MENDOZA': '038',
        'NECOCHEA': '040', 'PARANA': '041', 'PASO DE LOS LIBRES': '042',
        'POCITOS': '045', 'POSADAS': '046', 'PUERTO MADRYN': '047',
        'RIO GALLEGOS': '048', 'RIO GRANDE': '049', 'ROSARIO': '052',
        'SALTA': '053', 'SAN JAVIER': '054', 'SAN JUAN': '055',
        'SAN LORENZO': '057', 'SAN NICOLAS': '059', 'SAN PEDRO': '060',
        'SANTA CRUZ': '061', 'SANTA FE': '062', 'TINOGASTA': '066',
        'USHUAIA': '067', 'VILLA CONSTITUCION': '069', 'EZEIZA': '073',
        'TUCUMAN': '074', 'NEUQUEN': '075', 'ORAN': '076',
        'SAN RAFAEL': '078', 'LA RIOJA': '079', 'SAN ANTONIO OESTE': '080',
        'SAN LUIS': '083', 'SANTO TOME': '084', 'VILLA REGINA': '085',
        'OBERA': '086', 'CALETA OLIVIA': '087', 'GENERAL DEHEZA': '088',
        'SANTIAGO DEL ESTERO': '089', 'GENERAL PICO': '090',
        'BS.AS. NORTE': '091', 'BS.AS. SUR': '092', 'RAFAELA': '093',
        'MULTIADUANA': '099',
    }

    result = parsear_nro_despacho(text_norm_upper)
    if result:
        anio, aduana, tipo, nro, dc = result
        datos['nro_despacho'] = f"{tipo}{nro}{dc}"
        datos['anio'] = anio
        # FIX: el código de aduana (grupo 2) ya viene directamente del propio
        # número de despacho (ej: "26 073 IC04 080265 C" -> 073 = EZEIZA), es
        # confiable y NO se debe pisar con una búsqueda de nombre en todo el
        # texto del DI.
        datos['id_aduana'] = aduana
    else:
        alertas.append("❌ No se encontró número de despacho en el DI.")
        datos['nro_despacho'] = ''
        datos['anio'] = ''
        # Fallback: si no se pudo parsear el número de despacho, intentamos
        # recuperar la aduana buscando su nombre en el texto (mejor esto que nada).
        id_aduana = ''
        for nombre_aduana, codigo_aduana in ADUANAS.items():
            if nombre_aduana in text_norm_upper:
                id_aduana = codigo_aduana
                break
        datos['id_aduana'] = id_aduana

    fechas = re.findall(r'\b(\d{2}/\d{2}/\d{4})\b', text_norm)
    datos['fecha_nac'] = fechas[0] if fechas else ''
    if not fechas:
        alertas.append("❌ No se encontró fecha de oficialización en el DI.")

    cuits = re.findall(r'\b(\d{2}-\d{8}-\d)\b', text_norm)
    if cuits:
        datos['cuit_importador'] = cuits[0]
        datos['cuit_comprador'] = cuits[0]
    else:
        alertas.append("❌ No se encontró CUIT del importador en el DI.")
        datos['cuit_importador'] = ''
        datos['cuit_comprador'] = ''

    datos['cuit_despachante'] = cuits[1] if len(cuits) >= 2 else '20-22824212-9'
    if len(cuits) < 2:
        alertas.append("⚠️ No se encontró CUIT del despachante. Se usará el valor por defecto.")

    m = re.search(r'(FINNING\s+\S+(?:\s+\S+){1,3})', text_norm.upper())
    datos['importador'] = m.group(1).strip() if m else 'FINNING SOLUCIONES MINERAS SA'

    # ─ País de fabricación / procedencia, POR ÍTEM ─
    # FIX: en despachos con varios ítems (ej: el motor + repuestos sueltos
    # en el mismo DI), tomar el primer renglón "Origen País / Procedencia"
    # de TODO el texto puede traer el país de un ítem que no es el motor
    # (ej: tornillos clasificados en otra posición arancelaria). Acá se
    # identifican específicamente los ítems cuya posición SIM empieza con
    # 8408 o 8409 (motores de émbolo diesel/semi-diesel y sus partes, que
    # es la familia arancelaria de motores/blocks) y se extrae el país de
    # CADA uno de esos ítems puntualmente, en el orden en que aparecen.
    # `paises_por_item` queda disponible para que el flujo principal le
    # asigne a cada ENGINE/BLOCK cargado el país de su propio ítem del DI,
    # en vez de un único país "global" para todo el despacho.
    datos['paises_por_item'] = []
    # FIX (v3): antes se exigía que el número de ítem y "N" estuvieran
    # PEGADOS a la posición arancelaria (ej: "0058 N 8409.99.12.100C"). En
    # OCR a resoluciones más bajas, el layout de la tabla suele partir esto
    # en líneas distintas (aparece "Posición SIM / Código AFIP" en el
    # medio), así que ese ítem dejaba de reconocerse como motor/block por
    # completo y el país terminaba saliendo de OTRO ítem. Ahora se busca
    # directamente el patrón de posición 840[89] en cualquier parte del
    # texto, sin exigir que esté pegado al número de ítem.
    for m_item in re.finditer(r'840[89]\.\d{2}\.\d{2}\.\d{3}[A-Z]?', text_norm_upper):
        pos_after = m_item.end()
        # FIX (v2): antes se buscaba el renglón de países delimitándolo con
        # la palabra "UNIDAD" o "KILOGRAMO" como ancla de cierre. Eso falla
        # cuando el OCR pierde esa palabra puntual en la fila de un ítem
        # (pasa en documentos escaneados de baja calidad: el renglón
        # "Total Kg. Neto Origen Pais... Pais de Procedencia..." puede
        # salir incompleto, sin "Unidad/Estado"). Ahora se buscan los
        # nombres de país DIRECTAMENTE en una ventana de texto después de
        # la posición arancelaria del ítem, sin depender de esa palabra
        # ancla. Si el OCR además se comió una de las dos repeticiones del
        # país (pasa: a veces solo queda "ESTADOS UNIDOS" una vez en vez
        # de dos), igual funciona: con un solo país encontrado se asume
        # fabricación = procedencia (ya contemplado más abajo).
        chunk = text_norm_upper[pos_after:pos_after + 400]
        encontrados = extraer_codigos_pais(chunk, PAISES)
        codigos_ordenados = []
        for _, codigo in encontrados:
            if codigo not in codigos_ordenados:
                codigos_ordenados.append(codigo)
        if len(codigos_ordenados) >= 2:
            datos['paises_por_item'].append({
                'fabricacion': codigos_ordenados[0], 'procedencia': codigos_ordenados[1],
            })
        elif len(codigos_ordenados) == 1:
            datos['paises_por_item'].append({
                'fabricacion': codigos_ordenados[0], 'procedencia': codigos_ordenados[0],
            })

    if datos['paises_por_item']:
        # Compatibilidad hacia atrás: pais_fabricacion/procedencia "global"
        # quedan como el del primer ítem motor encontrado (sigue sirviendo
        # de fallback en despachos de un solo ítem).
        datos['pais_fabricacion'] = datos['paises_por_item'][0]['fabricacion']
        datos['pais_procedencia'] = datos['paises_por_item'][0]['procedencia']
    else:
        # Fallback: ningún ítem con posición 8408/8409 (documento atípico).
        # Se recurre al comportamiento anterior: primer renglón "Origen
        # País/Procedencia" que aparezca en el texto.
        datos['pais_procedencia'] = ''
        datos['pais_fabricacion'] = ''
        lines = text_norm_upper.split('\n')
        for i, line in enumerate(lines):
            if 'ORIGEN' in line and ('PROCEDENCIA' in line or 'PAIS' in line):
                if i + 1 < len(lines):
                    val_line = lines[i + 1].strip()
                    encontrados = extraer_codigos_pais(val_line, PAISES)
                    codigos_ordenados = []
                    for _, codigo in encontrados:
                        if codigo not in codigos_ordenados:
                            codigos_ordenados.append(codigo)
                    if len(codigos_ordenados) >= 2:
                        datos['pais_fabricacion'] = codigos_ordenados[0]
                        datos['pais_procedencia'] = codigos_ordenados[1]
                    elif len(codigos_ordenados) == 1:
                        datos['pais_fabricacion'] = codigos_ordenados[0]
                        datos['pais_procedencia'] = codigos_ordenados[0]
                    break

    if not datos['pais_procedencia']:
        _enc_fallback = extraer_codigos_pais(text_norm_upper, PAISES)
        if _enc_fallback:
            datos['pais_procedencia'] = _enc_fallback[0][1]
            if not datos['pais_fabricacion']:
                datos['pais_fabricacion'] = _enc_fallback[0][1]

    if not datos['pais_procedencia']:
        alertas.append("⚠️ No se encontró país de procedencia en el DI.")
    if not datos['pais_fabricacion']:
        alertas.append("⚠️ No se encontró país de fabricación en el DI.")

    datos['regimen'] = '20'

    # FIX: en vez de exigir literalmente "ZA(NNNN)" (el OCR lee la Z y la A
    # de formas muy distintas según el documento: a veces "Z.A(", a veces
    # directamente "74" en lugar de "ZA"), se ancla en la frase "AÑO DE
    # FABRICACION" —mucho más larga y difícil de leer mal que dos letras
    # sueltas— y se toman los dígitos que la preceden, quedándose con los
    # últimos 4 (el código siempre trae 2 ceros de relleno + el año).
    m = re.search(r'(\d+)\)\s*=\s*A[NÑ]O\s+DE\s+FABRICAC', text_norm.upper())
    datos['anio_fab_di'] = m.group(1)[-4:] if m else ''

    return datos, alertas


# ─── PARSEO DNRPA ───

# Los códigos de tipo son FIJOS en el sistema DNRPA (no dependen del OCR):
# 09 = BLOCK, 23 = MOTOR.
CODIGOS_TIPO_FIJOS = {'BLOCK': '09', 'MOTOR': '23'}

# Palabras de encabezado que aparecen siempre en la tabla "Consulta
# Marca-Tipo-Modelo" y que NO deben confundirse con la descripción de marca.
_DNRPA_STOPWORDS = {
    'CONSULTA', 'TABLA', 'MARCA', 'TIPO', 'TIPOS', 'MODELO', 'MODELOS',
    'CODIGO', 'CÓDIGO', 'DESCRIPCION', 'DESCRIPCIÓN', 'DENOMINACION',
    'DENOMINACIÓN', 'CERTIFICADO', 'PESO', 'UNIDAD', 'BLOCK', 'MOTOR',
}


def parsear_dnrpa(text, label=""):
    """
    El DNRPA suele ser una captura de pantalla (sin capa de texto), por lo
    que estos datos vienen siempre de OCR. El OCR puede reordenar las
    columnas de la tabla según la resolución/segmentación, así que en vez de
    depender de un único regex secuencial ("165 CATERPILLAR C52 C2.8" en ese
    orden exacto), buscamos cada dato de forma independiente en todo el
    texto. Esto es mucho más tolerante a que el OCR separe las columnas en
    líneas distintas.
    """
    datos = {}
    alertas = []
    text_upper = text.upper()

    # ─ ID de marca: primer número de 3 dígitos "suelto" en la página ─
    m_id = re.search(r'\b(\d{3})\b', text_upper)
    id_marca = m_id.group(1) if m_id else ''

    # ─ Descripción de marca: primera palabra de 4+ letras que no sea
    #   un encabezado de tabla conocido (ej: CATERPILLAR) ─
    palabras = re.findall(r'\b[A-ZÁÉÍÓÚÑ]{4,}\b', text_upper)
    candidatas = [p for p in palabras if p not in _DNRPA_STOPWORDS]
    marca_desc = candidatas[0] if candidatas else ''

    # ─ Modelo: patrones tipo "C52", "C2.8", "C2", etc. ─
    modelos = re.findall(r'\b([A-Z]{1,3}\d+(?:\.\d+)?)\b', text_upper)
    id_modelo = modelos[0] if modelos else ''
    cm_modelo = modelos[1] if len(modelos) > 1 else id_modelo

    if id_marca and marca_desc:
        datos['id_marca'] = id_marca
        datos['marca_desc'] = marca_desc
        datos['id_modelo'] = id_modelo
        datos['cm_modelo'] = cm_modelo
    else:
        alertas.append(f"❌ No se encontró marca/modelo en DNRPA {label}.")
        datos['id_marca'] = id_marca
        datos['id_modelo'] = id_modelo

    # ─ Tipos (BLOCK/MOTOR) ─
    # No dependemos de que el OCR lea correctamente el código numérico (23,
    # 09): esos códigos son fijos, así que solo necesitamos detectar la
    # palabra BLOCK o MOTOR en el texto.
    datos['tipos'] = {}
    for tipo_key, codigo_fijo in CODIGOS_TIPO_FIJOS.items():
        idx_tipo = text_upper.find(tipo_key)
        if idx_tipo == -1:
            continue
        contexto = text_upper[idx_tipo: idx_tipo + 200]
        peso_m = re.search(r'(\d[\d,\.]*)\s*(KGS?|C\.?C\.?)', contexto, re.IGNORECASE)
        peso = peso_m.group(1).replace(',', '').replace('.', '') if peso_m else ''
        datos['tipos'][tipo_key] = {'codigo': codigo_fijo, 'peso': peso}

    if not datos['tipos']:
        alertas.append(f"❌ No se encontraron tipos (BLOCK/MOTOR) en DNRPA {label}.")

    return datos, alertas


def _clean_celda_html(td):
    """Limpia el texto de una celda de la consulta DNRPA (saca &nbsp; y espacios extra)."""
    text = td.get_text()
    text = text.replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', text).strip()


def parsear_dnrpa_html(html_bytes, label=""):
    """
    Parseo del DNRPA cuando el operador sube el .htm/.html de la consulta
    "Marca-Tipo-Modelo" en vez de un PDF/captura. Es el camino preferido:
    el HTML trae el dato como texto real, no como imagen, así que no
    depende del OCR (nada de resoluciones, recortes ni capturas que fallan
    distinto cada vez).

    Estructura esperada (siempre la misma en esta consulta): las tablas de
    encabezado tienen bgcolor="#2B6D85" (celeste) y las tablas con la fila
    de datos real tienen bgcolor="#FFFFFF" (blanco). La primera tabla
    blanca es Marca/Modelo (4 celdas: id_marca, marca_desc, id_modelo,
    cm_modelo); la segunda es Tipos (4 celdas: código, denominación,
    certificado, peso unidad).
    """
    datos = {}
    alertas = []

    try:
        html_text = html_bytes.decode('utf-8')
    except UnicodeDecodeError:
        html_text = html_bytes.decode('latin-1', errors='ignore')

    soup = BeautifulSoup(html_text, 'html.parser')

    filas_blancas = []
    for table in soup.find_all('table'):
        bgcolor = (table.get('bgcolor') or '').upper()
        if bgcolor in ('#FFFFFF', '#FFF', 'WHITE'):
            for fila in table.find_all('tr'):
                celdas = [_clean_celda_html(td) for td in fila.find_all('td')]
                celdas = [c for c in celdas if c]
                if celdas:
                    filas_blancas.append(celdas)

    # ─ Marca / Modelo (primera fila blanca) ─
    if filas_blancas and len(filas_blancas[0]) >= 2:
        fila = filas_blancas[0]
        datos['id_marca'] = fila[0]
        datos['marca_desc'] = fila[1]
        datos['id_modelo'] = fila[2] if len(fila) > 2 else ''
        datos['cm_modelo'] = fila[3] if len(fila) > 3 else datos['id_modelo']
    else:
        alertas.append(f"❌ No se encontró marca/modelo en DNRPA {label} (HTML).")
        datos['id_marca'] = ''
        datos['id_modelo'] = ''

    # ─ Tipos (todas las filas blancas desde la segunda en adelante) ─
    # FIX: algunos motores tienen tanto código BLOCK como código MOTOR
    # (el mismo motor sirve para las dos consultas), entonces la tabla
    # "Tipos" trae DOS filas de datos, no una. Antes solo se leía
    # filas_blancas[1] y se perdía la segunda fila (ej: se guardaba BLOCK
    # y se ignoraba MOTOR, o viceversa). Ahora se recorren todas.
    datos['tipos'] = {}
    for fila in filas_blancas[1:]:
        if len(fila) < 2:
            continue
        codigo = fila[0]
        denominacion = fila[1].upper()
        peso_raw = fila[3] if len(fila) > 3 else (fila[2] if len(fila) > 2 else '')
        peso_m = re.search(r'(\d[\d.,]*)', peso_raw)
        peso = peso_m.group(1).replace('.', '').replace(',', '') if peso_m else ''

        if 'MOTOR' in denominacion:
            tipo_key = 'MOTOR'
        elif 'BLOCK' in denominacion:
            tipo_key = 'BLOCK'
        else:
            tipo_key = None

        if tipo_key:
            datos['tipos'][tipo_key] = {'codigo': codigo, 'peso': peso}

    if not datos['tipos']:
        alertas.append(f"❌ No se encontraron tipos (BLOCK/MOTOR) en DNRPA {label} (HTML).")

    return datos, alertas


def parsear_dnrpa_html_generico(html_bytes, label=""):
    """
    Variante genérica del parser de DNRPA .htm para clientes cuyo equipo NO
    se registra como MOTOR/BLOCK (ej: autoelevadoras — DNRPA código 37,
    denominación "AUTOELEVADORA"). A diferencia de parsear_dnrpa_html
    (Finning), acá NO se filtra por palabra clave en la denominación: se
    toma la fila de "Tipos" tal cual venga, sea cual sea su denominación
    (porque para este tipo de equipo la DNRPA no distingue motor/chasis —
    es un solo registro para la máquina entera).
    """
    datos = {}
    alertas = []

    try:
        html_text = html_bytes.decode('utf-8')
    except UnicodeDecodeError:
        html_text = html_bytes.decode('latin-1', errors='ignore')

    soup = BeautifulSoup(html_text, 'html.parser')

    filas_blancas = []
    for table in soup.find_all('table'):
        bgcolor = (table.get('bgcolor') or '').upper()
        if bgcolor in ('#FFFFFF', '#FFF', 'WHITE'):
            for fila in table.find_all('tr'):
                celdas = [_clean_celda_html(td) for td in fila.find_all('td')]
                celdas = [c for c in celdas if c]
                if celdas:
                    filas_blancas.append(celdas)

    if filas_blancas and len(filas_blancas[0]) >= 2:
        fila = filas_blancas[0]
        datos['id_marca'] = fila[0]
        datos['marca_desc'] = fila[1]
        datos['id_modelo'] = fila[2] if len(fila) > 2 else ''
        datos['cm_modelo'] = fila[3] if len(fila) > 3 else datos['id_modelo']
    else:
        alertas.append(f"❌ No se encontró marca/modelo en DNRPA {label} (HTML).")
        datos['id_marca'] = ''
        datos['id_modelo'] = ''

    datos['tipo_generico'] = {}
    if len(filas_blancas) >= 2:
        fila = filas_blancas[1]
        codigo = fila[0] if len(fila) > 0 else ''
        denominacion = fila[1] if len(fila) > 1 else ''
        peso_raw = fila[3] if len(fila) > 3 else (fila[2] if len(fila) > 2 else '')
        peso_m = re.search(r'(\d[\d.,]*)', peso_raw)
        peso = peso_m.group(1).replace('.', '').replace(',', '') if peso_m else ''
        datos['tipo_generico'] = {'codigo': codigo, 'denominacion': denominacion, 'peso': peso}
    else:
        alertas.append(f"❌ No se encontró la fila de Tipo en DNRPA {label} (HTML).")

    return datos, alertas


# ─── CLIENTE NUEVO (autoelevadoras / equipos con chasis) ───

# Posición SIM/AFIP para autoelevadoras/carretillas elevadoras. A diferencia
# de Finning (motores, familia 8408/8409), acá la familia arancelaria es
# 8427 (carretillas apiladoras y demás carretillas de manipulación).
POSICIONES_CLIENTE_NUEVO = ('8427',)


def extraer_datos_por_posicion(text, PAISES, prefijos, ventana=500, ventana_anio=2500):
    """
    Versión genérica (para clientes nuevos, no-Finning) de la búsqueda de
    país por ítem. Busca posiciones arancelarias que empiecen con
    cualquiera de los prefijos dados (ej: ('8427',) para autoelevadoras)
    en cualquier parte del texto —sin exigir que estén pegadas al número
    de ítem, por la misma razón que en Finning: el OCR a veces separa eso
    en líneas distintas—. Por cada posición encontrada, además de país,
    lee la Cantidad Unidades y el AÑO DE FABRICACIÓN declarados en ESE
    ítem puntual (no un año único global para todo el despacho, como
    hacía antes: cada ítem del DI puede traer un año distinto), y un
    fragmento de la Declaración de la Mercadería (para detectar más
    adelante si dice "motor eléctrico").

    Devuelve la lista YA EXPANDIDA según Cantidad Unidades: si un ítem del
    DI declara cantidad=2, esa entrada aparece 2 veces seguidas, para que
    se pueda repartir 1:1, en orden, con cada línea que el operador carga
    en la app (una por unidad física). Cada entrada incluye 'item_di'
    (1, 2, 3... según el orden de aparición de la posición en el DI, no
    el número de ítem literal) para poder mostrarle al operador de qué
    ítem del DI sale cada línea.
    """
    text_norm_upper = normalizar_ocr(text).upper()
    resultado = []
    pattern = r'(?:' + '|'.join(re.escape(p) for p in prefijos) + r')\.\d{2}\.\d{2}\.\d{3}[A-Z]?'
    matches = list(re.finditer(pattern, text_norm_upper))
    for idx_m, m_item in enumerate(matches):
        n_item_di = idx_m + 1
        pos_after = m_item.end()
        chunk = text_norm_upper[pos_after:pos_after + ventana]

        encontrados = extraer_codigos_pais(chunk, PAISES)
        codigos_ordenados = []
        for _, codigo in encontrados:
            if codigo not in codigos_ordenados:
                codigos_ordenados.append(codigo)
        if not codigos_ordenados:
            continue
        fabricacion = codigos_ordenados[0]
        procedencia = codigos_ordenados[1] if len(codigos_ordenados) >= 2 else codigos_ordenados[0]

        # FIX: la posición de "N,00" (la cantidad) respecto al encabezado
        # "CANTIDAD UNIDADES ESTADISTICAS" NO es fija — el OCR a veces la
        # imprime bien después del encabezado, pero en layouts de tabla
        # ancha (todos los encabezados en una línea, todos los valores en
        # la siguiente) puede terminar mucho más lejos, o incluso ANTES
        # del encabezado. En cambio, la cantidad siempre aparece pegada a
        # la palabra "UNIDAD" o "UNIDADES" (a veces es la unidad de medida
        # del ítem —"UNIDAD 2,00"—, a veces es el propio "CANTIDAD
        # UNIDADES\n2,00"), así que se ancla ahí en cualquiera de las dos
        # formas en vez de en un único punto fijo del encabezado.
        m_cant = re.search(r'\bUNIDAD(?:ES)?\b\s+(\d+),\d{2}', chunk)
        cantidad = int(m_cant.group(1)) if m_cant else 1

        # Año de fabricación DE ESTE ÍTEM puntual (mismo mecanismo robusto
        # que usa Finning vía "AÑO DE FABRICACION"). FIX: en PDFs con capa
        # de texto real (no escaneados), pdfplumber a veces extrae el
        # texto en un orden que NO respeta el orden visual de la página
        # (columnas superpuestas) — la anotación "ZA(...)" puede terminar
        # ANTES de la posición arancelaria en el texto extraído, aunque
        # visualmente esté después. Por eso ya no se busca solo hacia
        # adelante: se busca en toda la "zona" de este ítem, delimitada
        # por el ítem anterior y el siguiente (o los bordes del texto si
        # es el primero/último), así no se cruza a la zona de otro ítem.
        zona_ini = matches[idx_m - 1].end() if idx_m > 0 else max(0, m_item.start() - ventana_anio)
        zona_fin = matches[idx_m + 1].start() if idx_m + 1 < len(matches) else min(len(text_norm_upper), pos_after + ventana_anio)
        zona_item = text_norm_upper[zona_ini:zona_fin]
        m_anio = re.search(r'(\d+)\)\s*=\s*A[NÑ]O\s+DE\s+FABRICAC', zona_item)
        anio_item = m_anio.group(1)[-4:] if m_anio else ''

        idx_decl = text_norm_upper.find('DECLARACION DE LA MERCADERIA', pos_after)
        declaracion = text_norm_upper[idx_decl:idx_decl + 500] if idx_decl != -1 else ''
        # FIX: el OCR a veces conserva la tilde ("ELÉCTRICO") y a veces la
        # pierde ("ELECTRICO"); "ELECTRIC" sin tilde no matchea "ELÉCTRICO"
        # porque la É acentuada es un carácter distinto de la E simple.
        # Se chequean las dos variantes.
        es_electrico = 'ELECTRIC' in declaracion or 'ELÉCTRIC' in declaracion

        for _ in range(max(cantidad, 1)):
            resultado.append({
                'fabricacion': fabricacion, 'procedencia': procedencia,
                'anio_fabricacion': anio_item,
                'declaracion': declaracion, 'es_electrico': es_electrico,
                'item_di': n_item_di,
            })

    return resultado




def parsear_facturas_streaming(fc_files, n_engines):
    """
    FIX: antes se tomaba CUALQUIER "UNIQUE ID" encontrado en la factura,
    sin verificar que perteneciera a un ítem de motor. Si la factura
    trae otras partes con número de serie propio (no motores), se podían
    enganchar mal. Ahora se ancla en la palabra "ENGINE" de la
    descripción del ítem, y se busca el "UNIQUE ID" que aparece
    inmediatamente después de esa mención puntual — así, con varios
    motores en la misma factura (o en varias), cada uno se empareja con
    su propio número de serie en el orden en que aparecen los ítems
    ENGINE, sin depender de qué otro "UNIQUE ID" ajeno pueda haber en el
    documento.
    """
    motores = []
    for fc_f in fc_files:
        if len(motores) >= n_engines:
            break
        fc_bytes = fc_f.read()
        text_total = extract_text_pdfplumber(fc_bytes)
        if not text_total or len(text_total.strip()) <= 50:
            try:
                with pdfplumber.open(BytesIO(fc_bytes)) as pdf:
                    total_pages = len(pdf.pages)
            except:
                total_pages = 0
            texto_paginas = []
            for page_num in range(total_pages):
                texto_paginas.append(ocr_pdf_bytes(fc_bytes, f"fc_p{page_num}", dpi=200))
            text_total = "\n".join(texto_paginas)

        text_upper = text_total.upper()
        for m in re.finditer(r'\bENGINE\b', text_upper):
            if len(motores) >= n_engines:
                break
            ventana = text_upper[m.end():m.end() + 400]
            uid = re.search(r'UNIQUE\s+ID[:\s]+([A-Z0-9]+)', ventana)
            if uid and uid.group(1) not in motores:
                motores.append(uid.group(1))
    return motores


# ─── GENERAR TXT ───

def generar_txt(di, items_procesados, lcm_valor):
    try:
        fecha_dt = datetime.datetime.strptime(di['fecha_nac'], "%d/%m/%Y")
        anio_dos = str(fecha_dt.year)[-2:]
        fecha_str = fecha_dt.strftime("%d/%m/%Y")
    except:
        anio_dos = di.get('anio', '26')
        fecha_str = di.get('fecha_nac', '')

    nro_despacho = f"{di['nro_despacho']}/{anio_dos}"
    id_aduana = di.get('id_aduana', '001')

    if lcm_valor and lcm_valor.strip():
        parts = (re.split(r'[/\-\s]+', lcm_valor.strip()) + ["0","0","0"])[:3]
        lcm_tipo, lcm_nro, lcm_anio = parts
    else:
        lcm_tipo, lcm_nro, lcm_anio = "0", "0", "0"

    def q(v): return f'"{v}"'
    def safe(v): return str(v).strip().replace(" ", "") if v else ""

    caratula = ";".join([
        q(id_aduana), q(nro_despacho), q("00"), q("12"),
        q(di.get('cuit_importador','')), q("12"),
        q(di.get('cuit_comprador','')), q("12"),
        q(di.get('cuit_despachante','')), q(di.get('regimen','20')),
        q(fecha_str), q(di.get('pais_procedencia','212')),
        q(str(len(items_procesados))), q("N"), q("S"),
        q(""), q(""), q(""), q(""), q("")
    ])

    lineas = []
    for i, item in enumerate(items_procesados, start=1):
        dnrpa = item['dnrpa']
        tipo = item['tipo']
        if tipo in ('ENGINE', 'BLOCK'):
            tipo_key = 'MOTOR' if tipo == 'ENGINE' else 'BLOCK'
            id_tipo = dnrpa.get('tipos', {}).get(tipo_key, {}).get('codigo', '')
            peso = dnrpa.get('tipos', {}).get(tipo_key, {}).get('peso', '')
            nro_motor = safe(item.get('motor', '')) if tipo == 'ENGINE' else ''
            marca_motor = dnrpa.get('id_marca', '')
            marca_chasis = '000'
            nro_chasis = 'NOPOSEE'
        else:
            # Cliente nuevo (equipo genérico: autoelevadora, etc.). El
            # número de motor y/o chasis los tipea el operador a mano. Si
            # el ítem no tiene motor (o no se cargó su número), la marca
            # motor queda vacía y el número pasa a "NOPOSEE" —mismo
            # criterio que ya usa Finning para lo que no aplica—, y
            # simétricamente para chasis. La marca, cuando sí corresponde,
            # es la misma marca del equipo (DNRPA), salvo que el operador
            # la haya indicado distinta.
            id_tipo = dnrpa.get('tipo_generico', {}).get('codigo', '')
            peso = dnrpa.get('tipo_generico', {}).get('peso', '')
            nro_motor_raw = safe(item.get('nro_motor', ''))
            if nro_motor_raw:
                marca_motor = dnrpa.get('id_marca', '')
                nro_motor = nro_motor_raw
            else:
                marca_motor = ''
                nro_motor = 'NOPOSEE'
            nro_chasis_raw = safe(item.get('nro_chasis', ''))
            if nro_chasis_raw:
                marca_chasis = item.get('marca_chasis') or dnrpa.get('id_marca', '')
                nro_chasis = nro_chasis_raw
            else:
                marca_chasis = '000'
                nro_chasis = 'NOPOSEE'
        anio = str(item['anio_fab'])
        linea = ";".join([
            q(id_aduana), q(nro_despacho), q("00"), q(str(i)),
            q(dnrpa.get('id_marca','')), q(id_tipo), q(dnrpa.get('id_modelo','')),
            q(lcm_tipo), q(lcm_nro), q(lcm_anio),
            q(anio), q(anio),
            q(marca_motor), q(nro_motor),
            q(marca_chasis), q(nro_chasis),
            q(item.get('pais_fabricacion', di.get('pais_fabricacion', di.get('pais_procedencia','212')))),
            q(str(peso)), q("N")
        ])
        lineas.append(linea)

    return caratula + "\n" + "\n".join(lineas)


# ─── GENERAR EXCEL ───

def generar_excel(di, items_procesados, lcm_valor):
    wb = openpyxl.load_workbook(TEMPLATE_PATH)
    ws = wb['ANVERSO']

    try:
        fecha_dt = datetime.datetime.strptime(di['fecha_nac'], "%d/%m/%Y")
    except:
        fecha_dt = datetime.datetime.now()

    ws['E3'] = di['nro_despacho']
    ws['J3'] = fecha_dt
    ws['L3'] = di.get('regimen', '20')
    ws['E7'] = di.get('importador', '')
    ws['L7'] = di.get('cuit_importador', '')
    ws['I9'] = di.get('importador', '')
    ws['L9'] = di.get('cuit_comprador', '')
    try: ws['E11'] = int(di.get('pais_procedencia', 212))
    except: ws['E11'] = di.get('pais_procedencia', 212)

    for row_idx in range(16, 31):
        for col_idx in range(1, 14):
            ws.cell(row=row_idx, column=col_idx).value = None

    lcm_excel = lcm_valor.strip() if lcm_valor and lcm_valor.strip() else 'XXX'

    for i, item in enumerate(items_procesados):
        row = 16 + i
        dnrpa = item['dnrpa']
        tipo = item['tipo']
        if tipo in ('ENGINE', 'BLOCK'):
            tipo_key = 'MOTOR' if tipo == 'ENGINE' else 'BLOCK'
            id_tipo = dnrpa.get('tipos', {}).get(tipo_key, {}).get('codigo', '')
            peso = dnrpa.get('tipos', {}).get(tipo_key, {}).get('peso', '')
            nro_motor = item.get('motor', '') if tipo == 'ENGINE' else ''
            marca_motor = dnrpa.get('id_marca', '')
            marca_chasis = '000'
            nro_chasis = 'NO POSEE'
        else:
            # Cliente nuevo: número de motor/chasis tipeados a mano por el
            # operador. Si el ítem no tiene motor (o no se cargó su
            # número), la marca motor queda vacía y el número pasa a "NO
            # POSEE" —mismo criterio que ya usa Finning para lo que no
            # aplica—, y simétricamente para chasis.
            id_tipo = dnrpa.get('tipo_generico', {}).get('codigo', '')
            peso = dnrpa.get('tipo_generico', {}).get('peso', '')
            nro_motor_raw = item.get('nro_motor', '')
            if nro_motor_raw:
                marca_motor = dnrpa.get('id_marca', '')
                nro_motor = nro_motor_raw
            else:
                marca_motor = ''
                nro_motor = 'NO POSEE'
            nro_chasis_raw = item.get('nro_chasis', '')
            if nro_chasis_raw:
                marca_chasis = item.get('marca_chasis') or dnrpa.get('id_marca', '')
                nro_chasis = nro_chasis_raw
            else:
                marca_chasis = '000'
                nro_chasis = 'NO POSEE'
        anio = str(item['anio_fab'])

        ws.cell(row=row, column=1).value = i + 1
        ws.cell(row=row, column=2).value = dnrpa.get('id_marca','')
        ws.cell(row=row, column=3).value = id_tipo
        ws.cell(row=row, column=4).value = dnrpa.get('id_modelo','')
        ws.cell(row=row, column=5).value = lcm_excel
        ws.cell(row=row, column=6).value = anio
        ws.cell(row=row, column=7).value = anio
        ws.cell(row=row, column=8).value = marca_motor
        ws.cell(row=row, column=9).value = nro_motor
        ws.cell(row=row, column=10).value = marca_chasis
        ws.cell(row=row, column=11).value = nro_chasis
        ws.cell(row=row, column=12).value = item.get('pais_fabricacion', di.get('pais_fabricacion', di.get('pais_procedencia','212')))
        ws.cell(row=row, column=13).value = str(peso)

    ws['D35'] = 'CAPITAL FEDERAL'
    ws['E37'] = datetime.datetime.now()

    ADUANAS_NOMBRE = {
        '001': '001-BS.AS. CAPITAL', '003': '003-BAHIA BLANCA', '004': '004-BARILOCHE',
        '008': '008-CAMPANA', '017': '017-CORDOBA', '029': '029-IGUAZU',
        '033': '033-LA PLATA', '037': '037-MAR DEL PLATA', '038': '038-MENDOZA',
        '052': '052-ROSARIO', '053': '053-SALTA', '055': '055-SAN JUAN',
        '073': '073-EZEIZA', '074': '074-TUCUMAN', '075': '075-NEUQUEN',
        '091': '091-BS.AS. NORTE', '092': '092-BS.AS. SUR',
    }
    id_aduana = di.get('id_aduana', '001')
    ws['D31'] = ADUANAS_NOMBRE.get(id_aduana, f"{id_aduana}-")

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════
# INTERFAZ
# ═══════════════════════════════════════════════

st.markdown('<p class="section-title">0 · Cliente</p>', unsafe_allow_html=True)
cliente = st.radio("Cliente", ["Finning", "Coca-Cola"], horizontal=True)

# Nombre fijo del importador y posiciones arancelarias propias de cada
# cliente nuevo (no-Finning). Se suman acá a medida que se incorporan más
# clientes, sin tocar la lógica de Finning.
IMPORTADOR_FIJO = {
    "Coca-Cola": "SERVICIOS Y PRODUCTOS PARA BEBIDAS REFRESCANTES S.R.L.",
}
POSICIONES_POR_CLIENTE = {
    "Coca-Cola": POSICIONES_CLIENTE_NUEVO,  # ('8427',) — autoelevadoras
}

st.markdown('<p class="section-title">1 · Documentos generales</p>', unsafe_allow_html=True)
if cliente == "Finning":
    col1, col2 = st.columns(2)
    with col1:
        di_file = st.file_uploader("📋 DI (PDF)", type="pdf")
    with col2:
        fc_files = st.file_uploader("🧾 Factura/s (PDF)", type="pdf", accept_multiple_files=True)
else:
    # Clientes nuevos: solo el DI. No hay factura de la que sacar números
    # de motor (se tipean a mano por ítem, más abajo).
    di_file = st.file_uploader("📋 DI (PDF)", type="pdf")
    fc_files = []

# ── Vista previa del DI para clientes nuevos ──
# Se parsea apenas se sube el archivo (no recién al tocar "Procesar y
# Generar"), para poder auto-generar la cantidad correcta de ítems y
# mostrar al lado de cada uno su país, año y un fragmento de la
# Declaración de la Mercadería. Se cachea en session_state para no
# repetir el OCR en cada rerun de Streamlit mientras se cargan los ítems.
datos_items_cliente_nuevo = []
if cliente != "Finning" and di_file is not None:
    di_key = f"{di_file.name}_{di_file.size}"
    if st.session_state.get('preview_di_key') != di_key:
        with st.spinner("Leyendo DI..."):
            di_bytes_preview = di_file.getvalue()
            prefijos_preview = POSICIONES_POR_CLIENTE.get(cliente, ('8427',))
            di_text_preview = get_text_di(di_bytes_preview, "di_preview", dpi=150)
            datos_preview = extraer_datos_por_posicion(di_text_preview, PAISES, prefijos_preview)

            # Si algún ítem quedó sin año de fabricación, es probable que
            # el OCR a 150dpi haya deformado la etiqueta "ZA(NNNN)" (pasa
            # en DIs 100% imagen, ej: "ZA(" leído como "74("). Reintentamos
            # UNA sola vez a mayor resolución antes de mostrarle nada al
            # operador.
            if any(not d.get('anio_fabricacion') for d in datos_preview):
                di_text_preview_hi = get_text_di(di_bytes_preview, "di_preview_hi", dpi=250)
                datos_preview_hi = extraer_datos_por_posicion(di_text_preview_hi, PAISES, prefijos_preview)
                if len(datos_preview_hi) >= len(datos_preview) and all(
                    d.get('anio_fabricacion') for d in datos_preview_hi
                ):
                    datos_preview = datos_preview_hi

            st.session_state['preview_di_key'] = di_key
            st.session_state['preview_datos_items'] = datos_preview
            # Auto-generar la cantidad de ítems detectada en el DI (una
            # unidad física = una línea) — el operador puede seguir
            # ajustando a mano con Agregar/Quitar si hace falta.
            if datos_preview:
                st.session_state.n_items = len(datos_preview)
    datos_items_cliente_nuevo = st.session_state.get('preview_datos_items', [])


st.markdown('<p class="section-title">2 · Ítems de la DJIM</p>', unsafe_allow_html=True)
if cliente == "Finning":
    st.caption("Agregá un ítem por cada motor o block del despacho.")
else:
    st.caption("Agregá un ítem por cada unidad física del despacho.")

col_add, col_rem = st.columns([1, 1])
with col_add:
    if st.button("➕ Agregar ítem"):
        st.session_state.n_items += 1
with col_rem:
    if st.session_state.n_items > 0:
        if st.button("➖ Quitar último"):
            st.session_state.n_items -= 1

tipos_seleccionados = []
dnrpa_files = []
anios_block = []
nros_motor_manual = []
nros_chasis_manual = []

for idx in range(st.session_state.n_items):
    st.markdown(f"**Ítem {idx+1}**")

    if cliente == "Finning":
        col1, col2 = st.columns([1, 2])
        with col1:
            tipo = st.selectbox("Tipo", ["ENGINE", "BLOCK"], key=f"tipo_sel_{idx}")
            tipos_seleccionados.append(tipo)
            if tipo == "BLOCK":
                anio = st.text_input("Año fabricación", key=f"anio_sel_{idx}", placeholder="ej: 2025")
                anios_block.append(anio)
            else:
                anios_block.append("")
        with col2:
            dnrpa = st.file_uploader(
                "DNRPA (.htm recomendado, o PDF)",
                type=["htm", "html", "pdf"],
                key=f"dnrpa_sel_{idx}",
            )
            dnrpa_files.append(dnrpa)
        nros_motor_manual.append("")
        nros_chasis_manual.append("")

    else:
        # Cliente nuevo (Coca-Cola, etc.): país y año de fabricación
        # salen del DI (ya no son editables acá — se leyeron correctamente
        # por posición arancelaria y por ítem, más arriba); el operador
        # solo elige qué datos tiene el equipo —motor, chasis, o ambos— y
        # los tipea a mano. Se pre-selecciona "Chasis" si la Declaración
        # de la Mercadería del ítem correspondiente del DI menciona
        # "motor eléctrico" (el operador siempre puede cambiarlo).
        tipos_seleccionados.append("GENERICO")
        anios_block.append("")  # el año sale del DI para este cliente, no es manual

        datos_di_item = datos_items_cliente_nuevo[idx] if idx < len(datos_items_cliente_nuevo) else None

        default_idx = 0  # "Motor y Chasis" por defecto
        opciones = ["Motor y Chasis", "Chasis", "Motor"]
        if datos_di_item and datos_di_item.get('es_electrico'):
            default_idx = 1  # "Chasis"

        col1, col2 = st.columns([1, 2])
        with col1:
            if datos_di_item:
                st.caption(
                    f"Del ítem N° {datos_di_item['item_di']} del DI — "
                    f"País: {datos_di_item['fabricacion']} · "
                    f"Año fabricación: {datos_di_item.get('anio_fabricacion') or '⚠️ no encontrado'}"
                )
            else:
                st.caption("⚠️ Este ítem no coincide con ninguna unidad detectada en el DI — verificar a mano.")
            eleccion = st.selectbox(
                "Datos disponibles", opciones, index=default_idx, key=f"tipo_cliente_nuevo_{idx}"
            )
            nro_motor_val = ""
            nro_chasis_val = ""
            if eleccion in ("Motor", "Motor y Chasis"):
                nro_motor_val = st.text_input("Número de motor", key=f"nro_motor_{idx}")
            if eleccion in ("Chasis", "Motor y Chasis"):
                nro_chasis_val = st.text_input("Número de chasis", key=f"nro_chasis_{idx}")
            nros_motor_manual.append(nro_motor_val)
            nros_chasis_manual.append(nro_chasis_val)
        with col2:
            dnrpa = st.file_uploader(
                "DNRPA (.htm recomendado, o PDF)",
                type=["htm", "html", "pdf"],
                key=f"dnrpa_sel_{idx}",
            )
            dnrpa_files.append(dnrpa)
            if datos_di_item and datos_di_item.get('es_electrico'):
                st.caption("🔎 Se detectó \"motor eléctrico\" en este ítem del DI.")
    st.divider()


st.markdown('<p class="section-title">3 · Datos adicionales</p>', unsafe_allow_html=True)
col1, col2 = st.columns(2)
with col1:
    tiene_lcm = st.radio("¿Tiene LCM?", ["No", "Sí"], horizontal=True)
with col2:
    lcm_valor = ""
    if tiene_lcm == "Sí":
        lcm_valor = st.text_input("Número LCM", placeholder="ej: 39/12345/2025")

if cliente == "Finning":
    es_mineria = st.radio("¿Minería?", ["No", "Sí"], horizontal=True)
else:
    # No aplica para este cliente: el Régimen de Importación es siempre "20".
    es_mineria = "No"

st.markdown("---")

if st.button("⚙️ Procesar y Generar", type="primary", use_container_width=True):

    errores = []
    if not di_file:
        errores.append("❌ Faltá subir el DI.")
    if cliente == "Finning" and not fc_files:
        errores.append("❌ Faltá subir al menos una factura.")
    if st.session_state.n_items == 0:
        errores.append("❌ Agregá al menos un ítem.")
    for idx in range(st.session_state.n_items):
        if not dnrpa_files[idx]:
            errores.append(f"❌ Faltá el DNRPA del ítem {idx+1}.")
        if cliente == "Finning" and tipos_seleccionados[idx] == 'BLOCK' and not anios_block[idx].strip():
            errores.append(f"❌ Ingresá el año de fabricación del ítem {idx+1} (BLOCK).")
        if cliente != "Finning" and not nros_motor_manual[idx].strip() and not nros_chasis_manual[idx].strip():
            errores.append(f"❌ Ingresá número de motor y/o de chasis para el ítem {idx+1}.")

    if errores:
        for e in errores:
            st.error(e)
        st.stop()

    with st.spinner("Procesando documentos..."):
        di_bytes = di_file.read()
        di_text = get_text_di(di_bytes, "di", dpi=150)
        di_datos, di_alertas = parsear_di(di_text)

        # Si no se encontró año de fabricación y hay al menos un ENGINE
        # cargado (Finning) o el cliente es uno nuevo (siempre necesita año
        # de fabricación del DI), es probable que el OCR a 150dpi haya
        # perdido la etiqueta "ZA(NNNN)" (pasa en DIs 100% imagen donde esa
        # zona del formulario tiene interferencia visual, ej. la marca de
        # agua de fondo). Reintentamos UNA sola vez a mayor resolución
        # antes de reportar error.
        hay_engine = any(t == 'ENGINE' for t in tipos_seleccionados)
        necesita_anio_di = hay_engine or cliente != "Finning"
        if necesita_anio_di and not di_datos.get('anio_fab_di'):
            di_text_hi = get_text_di(di_bytes, "di_hi", dpi=250)
            di_datos_hi, di_alertas_hi = parsear_di(di_text_hi)
            if di_datos_hi.get('anio_fab_di'):
                di_datos, di_alertas = di_datos_hi, di_alertas_hi
                di_text = di_text_hi

        # Si el operador marca "Minería" (solo Finning), el Código Régimen
        # de Importación pasa de "20" (el general) a "Z", tanto en el
        # Excel como en el .txt.
        if es_mineria == "Sí":
            di_datos['regimen'] = 'Z'

        # Clientes nuevos: nombre de importador fijo (no se infiere del DI,
        # que suele venir recortado/con errores de OCR) y régimen siempre "20".
        if cliente in IMPORTADOR_FIJO:
            di_datos['importador'] = IMPORTADOR_FIJO[cliente]
            di_datos['regimen'] = '20'

        items_procesados = []
        todas_alertas = di_alertas.copy()

        if cliente == "Finning":
            n_engines = sum(1 for t in tipos_seleccionados if t == 'ENGINE')
            motores_factura = parsear_facturas_streaming(fc_files, n_engines)

            motor_idx = 0
            paises_item_idx = 0

            for idx in range(st.session_state.n_items):
                tipo = tipos_seleccionados[idx]
                tipo_key = 'MOTOR' if tipo == 'ENGINE' else 'BLOCK'

                dnrpa_bytes = dnrpa_files[idx].read()
                dnrpa_nombre = (dnrpa_files[idx].name or "").lower()

                if dnrpa_nombre.endswith(".htm") or dnrpa_nombre.endswith(".html"):
                    # Camino preferido: el HTML de la consulta DNRPA trae el dato
                    # como texto real, sin depender de OCR.
                    dnrpa_datos, dnrpa_alertas = parsear_dnrpa_html(dnrpa_bytes, f"ítem {idx+1}")
                else:
                    # Fallback para capturas/PDF viejos: psm=6 + upscale=3 porque
                    # el DNRPA en PDF suele ser una captura de pantalla de baja
                    # resolución; agrandamos la imagen y forzamos modo de
                    # segmentación de bloque uniforme para mejorar el OCR.
                    dnrpa_text = get_text(dnrpa_bytes, f"dnrpa_{idx}", dpi=250, psm=6, upscale=3)
                    dnrpa_datos, dnrpa_alertas = parsear_dnrpa(dnrpa_text, f"ítem {idx+1}")

                todas_alertas.extend(dnrpa_alertas)

                if tipo == 'ENGINE':
                    anio_fab = di_datos.get('anio_fab_di', '')
                    if not anio_fab:
                        todas_alertas.append(f"❌ No se encontró año de fabricación en el DI para ENGINE ítem {idx+1}.")
                else:
                    anio_fab = anios_block[idx]

                motor = ''
                if tipo == 'ENGINE':
                    if motor_idx < len(motores_factura):
                        motor = motores_factura[motor_idx]
                        motor_idx += 1
                    else:
                        todas_alertas.append(f"⚠️ No se encontró UNIQUE ID para ENGINE ítem {idx+1}.")

                if not dnrpa_datos.get('tipos',{}).get(tipo_key,{}).get('peso'):
                    todas_alertas.append(f"❌ No se encontró peso para {tipo} en DNRPA ítem {idx+1}.")

                # País de fabricación/procedencia de ESTE ítem puntual: si el DI
                # tiene varios ítems con posición 8408/8409 (motor + repuestos
                # en el mismo despacho), cada ENGINE/BLOCK cargado toma el país
                # del ítem del DI que le corresponde en orden, no un país
                # "global" único para todo el despacho.
                paises_item = di_datos.get('paises_por_item') or []
                if paises_item_idx < len(paises_item):
                    pais_fab_item = paises_item[paises_item_idx]['fabricacion']
                    paises_item_idx += 1
                else:
                    pais_fab_item = di_datos.get('pais_fabricacion', di_datos.get('pais_procedencia', '212'))

                items_procesados.append({
                    'tipo': tipo, 'dnrpa': dnrpa_datos,
                    'anio_fab': anio_fab, 'motor': motor,
                    'pais_fabricacion': pais_fab_item,
                })

            if n_engines > len(motores_factura):
                todas_alertas.append(
                    f"⚠️ Se declararon {n_engines} ENGINE(s) pero se encontraron "
                    f"solo {len(motores_factura)} UNIQUE ID(s). Verificar manualmente."
                )

        else:
            # ── Cliente nuevo (Coca-Cola, etc.): equipos con motor y/o
            # chasis tipeados a mano, país Y AÑO por posición propia del
            # cliente (ej: 8427), expandido según Cantidad Unidades del
            # DI. Cada ítem del DI puede traer un país y un año distintos
            # —no se usa un valor "global" único para todo el despacho—.
            prefijos_cliente = POSICIONES_POR_CLIENTE.get(cliente, ('8427',))
            datos_items = extraer_datos_por_posicion(di_text, PAISES, prefijos_cliente)

            # Mismo reintento a mayor resolución que Finning, pero acá
            # aplicado por ítem: si a alguno le falta el año, reintentamos
            # el DI completo a 250dpi antes de reportar error.
            if any(not d.get('anio_fabricacion') for d in datos_items):
                di_text_hi_cn = get_text_di(di_bytes, "di_hi_cn", dpi=250)
                datos_items_hi = extraer_datos_por_posicion(di_text_hi_cn, PAISES, prefijos_cliente)
                if len(datos_items_hi) >= len(datos_items) and all(
                    d.get('anio_fabricacion') for d in datos_items_hi
                ):
                    datos_items = datos_items_hi

            if not datos_items:
                todas_alertas.append(
                    f"❌ No se encontró ninguna posición {prefijos_cliente[0]} en el DI — "
                    f"cargar país y año de fabricación manualmente y verificar."
                )

            for idx in range(st.session_state.n_items):
                dnrpa_bytes = dnrpa_files[idx].read()
                dnrpa_nombre = (dnrpa_files[idx].name or "").lower()

                if dnrpa_nombre.endswith(".htm") or dnrpa_nombre.endswith(".html"):
                    dnrpa_datos, dnrpa_alertas = parsear_dnrpa_html_generico(dnrpa_bytes, f"ítem {idx+1}")
                else:
                    # Fallback en PDF/captura: reutiliza el parseo de
                    # marca/modelo genérico, pero no puede confirmar el
                    # código de tipo/peso sin la palabra MOTOR/BLOCK —
                    # se avisa para que se cargue a mano.
                    dnrpa_text = get_text(dnrpa_bytes, f"dnrpa_{idx}", dpi=250, psm=6, upscale=3)
                    dnrpa_datos, dnrpa_alertas = parsear_dnrpa(dnrpa_text, f"ítem {idx+1}")
                    dnrpa_datos['tipo_generico'] = {}
                    dnrpa_alertas.append(
                        f"⚠️ DNRPA ítem {idx+1} en PDF: no se pudo leer el código de tipo ni el "
                        f"peso automáticamente (subí el .htm de la consulta si es posible)."
                    )

                todas_alertas.extend(dnrpa_alertas)

                if not dnrpa_datos.get('tipo_generico', {}).get('peso'):
                    todas_alertas.append(f"❌ No se encontró peso en DNRPA ítem {idx+1}.")

                if idx < len(datos_items):
                    pais_fab_item = datos_items[idx]['fabricacion']
                    anio_fab_item = datos_items[idx].get('anio_fabricacion', '')
                    if not anio_fab_item:
                        todas_alertas.append(
                            f"❌ No se encontró año de fabricación en el DI para el ítem {idx+1}."
                        )
                else:
                    pais_fab_item = di_datos.get('pais_fabricacion', '')
                    anio_fab_item = ''
                    todas_alertas.append(
                        f"⚠️ Ítem {idx+1}: no coincide con ninguna unidad detectada en el DI "
                        f"(cargaste más ítems de los que el DI declara) — verificar país y año a mano."
                    )

                items_procesados.append({
                    'tipo': 'GENERICO', 'dnrpa': dnrpa_datos,
                    'anio_fab': anio_fab_item,
                    'nro_motor': nros_motor_manual[idx],
                    'nro_chasis': nros_chasis_manual[idx],
                    'pais_fabricacion': pais_fab_item,
                })

            if len(datos_items) not in (0, st.session_state.n_items):
                todas_alertas.append(
                    f"⚠️ El DI declara {len(datos_items)} unidad(es) (según Cantidad Unidades) "
                    f"pero cargaste {st.session_state.n_items} ítem(s). Verificar que coincida."
                )

        st.session_state['resultado_txt'] = generar_txt(di_datos, items_procesados, lcm_valor)
        if os.path.exists(TEMPLATE_PATH):
            excel_buf = generar_excel(di_datos, items_procesados, lcm_valor)
            st.session_state['resultado_excel'] = excel_buf.read()
            st.session_state['resultado_nro'] = di_datos.get('nro_despacho', 'DJIM')

    for a in [x for x in todas_alertas if x.startswith("⚠️")]:
        st.warning(a)

    errores_criticos = [x for x in todas_alertas if x.startswith("❌")]
    if errores_criticos:
        for e in errores_criticos:
            st.error(e)
        st.stop()

    st.markdown('<div class="alerta-ok">✅ Documentos procesados correctamente.</div>', unsafe_allow_html=True)
    st.markdown("")

    with st.expander("📋 Ver datos extraídos"):
        st.markdown("**DI:**")
        st.json({k: v for k, v in di_datos.items() if k != 'anio_fab_di'})
        for idx, item in enumerate(items_procesados):
            st.markdown(f"**Ítem {idx+1} — {item['tipo']}:**")
            st.json({
                'id_marca': item['dnrpa'].get('id_marca'),
                'id_modelo': item['dnrpa'].get('id_modelo'),
                'tipos': item['dnrpa'].get('tipos') or item['dnrpa'].get('tipo_generico'),
                'anio_fab': item['anio_fab'],
                'motor': item.get('motor', item.get('nro_motor', '')),
                'chasis': item.get('nro_chasis', ''),
                'pais_fabricacion': item.get('pais_fabricacion', ''),
            })

# ── DESCARGAS PERSISTENTES ──
if 'resultado_txt' in st.session_state or 'resultado_excel' in st.session_state:
    st.markdown('<p class="section-title">4 · Descargar</p>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        if 'resultado_txt' in st.session_state:
            st.download_button(
                "📥 DJIM Electrónica (.txt)",
                data=st.session_state['resultado_txt'].encode('utf-8'),
                file_name="DJIM_ELECTRONICA.txt",
                mime="text/plain",
                use_container_width=True,
                key="dl_txt"
            )
    with col2:
        if 'resultado_excel' in st.session_state:
            nro = st.session_state.get('resultado_nro', 'DJIM')
            st.download_button(
                "📥 DJIM Excel (.xlsx)",
                data=st.session_state['resultado_excel'],
                file_name=f"DJIM_{nro}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="dl_excel"
            )

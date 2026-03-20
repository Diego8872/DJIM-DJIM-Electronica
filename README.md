# DJIM / DJIM Electrónica

Generador automático de DJIM (Excel) y DJIM Electrónica (TXT) para trámites de importación de motores y bloques.

## Documentos requeridos
- **DI PDF**: Despacho de importación (página de carátula)
- **Factura PDF**: Factura Caterpillar con ítems ENGINE o BLOCK
- **DNRPA PDF**: Consulta Marca-Tipo-Modelo de la DNRPA

## Flujo
1. Subir los 3 PDFs
2. Completar datos del operador (tipo, años, LCM)
3. Descargar DJIM Excel + DJIM Electrónica TXT

## Notas
- El template `template_djim.xlsx` debe estar en el root del repo
- Tesseract OCR se usa como fallback para PDFs escaneados

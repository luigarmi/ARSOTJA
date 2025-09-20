from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

def gen_payment_receipt_pdf(path: str, pago, loan, customer, company_name="ARGSOJA"):
    c = canvas.Canvas(path, pagesize=LETTER)
    w, h = LETTER; y = h - 30*mm
    c.setFont("Helvetica-Bold", 14); c.drawString(25*mm, y, f"{company_name} - Recibo de Pago"); y-=10*mm
    c.setFont("Helvetica", 10)
    c.drawString(25*mm, y, f"Fecha: {pago.date.isoformat()}    Recibo ID: {pago.id}"); y-=6*mm
    c.drawString(25*mm, y, f"Cliente: {customer.name}    Doc: {customer.document or ''}"); y-=6*mm
    c.drawString(25*mm, y, f"Préstamo #{loan.id} | Frecuencia: {loan.frequency} | Tasa mensual: {loan.monthly_rate:.2%}"); y-=10*mm
    c.setFont("Helvetica-Bold", 12); c.drawString(25*mm, y, f"Monto pagado: ${pago.amount:,.2f}"); y-=8*mm
    c.setFont("Helvetica", 10); c.drawString(25*mm, y, f"Método: {pago.method or ''}"); y-=6*mm
    if pago.note: c.drawString(25*mm, y, f"Nota: {pago.note}"); y-=6*mm
    c.setFont("Helvetica-Oblique", 9); y-=10*mm; c.drawString(25*mm, y, "Documento generado automáticamente desde ARGSOJA.")
    c.showPage(); c.save()

def gen_statement_pdf(path: str, loan, customer, schedule, totals, company_name="ARGSOJA"):
    c = canvas.Canvas(path, pagesize=LETTER)
    w, h = LETTER; y = h - 25*mm
    c.setFont("Helvetica-Bold", 14); c.drawString(25*mm, y, f"{company_name} - Estado de Cuenta"); y-=10*mm
    c.setFont("Helvetica", 10)
    c.drawString(25*mm, y, f"Cliente: {customer.name}    Doc: {customer.document or ''}"); y-=6*mm
    c.drawString(25*mm, y, f"Préstamo #{loan.id} | Inicio: {loan.start_date.isoformat()} | Plazo: {loan.term_months} mes(es) | Frecuencia: {loan.frequency}"); y-=6*mm
    c.drawString(25*mm, y, f"Principal: ${loan.principal:,.2f} | Tasa mensual: {loan.monthly_rate:.2%}"); y-=10*mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(25*mm, y, f"Resumen: Cuota: ${totals['quota_periodica']:,.2f}  |  Total a pagar: ${totals['total_due']:,.2f}  |  Saldo: ${totals['balance']:,.2f}")
    y-=10*mm; c.setFont("Helvetica-Bold", 10); c.drawString(25*mm, y, "Cronograma (parcial):"); y-=6*mm; c.setFont("Helvetica", 9)
    c.drawString(25*mm, y, "N"); c.drawString(35*mm, y, "Fecha"); c.drawString(65*mm, y, "Cuota"); c.drawString(90*mm, y, "Interés"); c.drawString(115*mm, y, "Capital"); c.drawString(140*mm, y, "Cap. Pend."); y-=6*mm
    for r in schedule[:20]:
        c.drawString(25*mm, y, str(r["n"])); c.drawString(35*mm, y, r["date"].isoformat()); c.drawString(65*mm, y, f"${r['quota']:,.2f}")
        c.drawString(90*mm, y, f"${r['interest']:,.2f}"); c.drawString(115*mm, y, f"${r['principal']:,.2f}"); c.drawString(140*mm, y, f"${r['capital_pendiente']:,.2f}")
        y-=5*mm
        if y < 30*mm: c.showPage(); y = h - 25*mm; c.setFont("Helvetica", 9)
    c.setFont("Helvetica-Oblique", 9); c.drawString(25*mm, 20*mm, "Documento generado automáticamente desde ARGSOJA.")
    c.showPage(); c.save()

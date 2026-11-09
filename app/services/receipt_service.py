import io
from flask import current_app, render_template_string

try:
    from weasyprint import HTML
    _HAS_WEASY = True
except Exception:
    _HAS_WEASY = False

try:
    import qrcode
    _HAS_QR = True
except Exception:
    _HAS_QR = False

_RECEIPT_HTML = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page { size: 80mm auto; margin: 6mm 4mm; }
  body { font-family: Inter, Arial, sans-serif; color: #111; font-size: 11px; }
  .center { text-align: center; }
  .pharmacy { font-weight: 700; font-size: 15px; margin: 2px 0; }
  hr { border: none; border-top: 1px dashed #999; margin: 8px 0; }
  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 3px 0; font-size: 10.5px; }
  th { text-align: left; border-bottom: 1px solid #ddd; }
  .right { text-align: right; }
  .totals td { padding: 2px 0; }
  .grand { font-weight: 700; font-size: 13px; border-top: 1px solid #000; padding-top: 4px; }
  .footer { margin-top: 10px; text-align: center; color: #555; font-size: 10px; }
</style>
</head>
<body>
  <div class="center">
    <div class="pharmacy">{{ tenant.pharmacy_name }}</div>
    {% if tenant.address %}<div>{{ tenant.address }}</div>{% endif %}
    {% if tenant.owner_phone %}<div>Tel: {{ tenant.owner_phone }}</div>{% endif %}
  </div>
  <hr>
  <div><strong>Receipt:</strong> {{ sale.receipt_no }}</div>
  <div><strong>Date:</strong> {{ sale.timestamp }}</div>
  <div><strong>Cashier:</strong> {{ sale.cashier_name }}</div>
  <hr>
  <table>
    <thead>
      <tr><th>Item</th><th class="right">Qty</th><th class="right">Price</th><th class="right">Sub</th></tr>
    </thead>
    <tbody>
      {% for it in sale['items'] %}
      <tr>
        <td>{{ it.name }}</td>
        <td class="right">{{ it.qty }}</td>
        <td class="right">{{ "%.2f"|format(it.price) }}</td>
        <td class="right">{{ "%.2f"|format(it.line_subtotal) }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  <hr>
  <table class="totals">
    <tr><td>Subtotal</td><td class="right">GH₵ {{ "%.2f"|format(sale.subtotal) }}</td></tr>
    <tr><td>VAT</td><td class="right">GH₵ {{ "%.2f"|format(sale.vat) }}</td></tr>
    <tr class="grand"><td>Total</td><td class="right">GH₵ {{ "%.2f"|format(sale.total_amount) }}</td></tr>
  </table>
  <div class="footer">{{ tenant.receipt_footer or "Thank you. Get well soon!" }}<br>Powered by Pharmacole</div>
</body>
</html>
"""

def render_receipt_html(tenant, sale, branch_name=None):
    return render_template_string(
        _RECEIPT_HTML,
        tenant=tenant,
        sale=sale,
        branch_name=branch_name,
    )

def receipt_pdf(tenant, sale, branch_name=None) -> bytes:
    if not _HAS_WEASY:
        # Return None instead of crashing if WeasyPrint isn't installed on Windows
        return None 
    try:
        html = render_receipt_html(tenant, sale, branch_name)
        return HTML(string=html).write_pdf()
    except Exception as e:
        current_app.logger.error(f"PDF Generation failed: {e}")
        return None
import io
from datetime import datetime
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
  .logo { max-height: 60px; max-width: 100%; margin-bottom: 6px; }
  .pharmacy { font-weight: 700; font-size: 15px; margin: 2px 0; }
  .muted { color: #666; }
  hr { border: none; border-top: 1px dashed #999; margin: 8px 0; }
  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 3px 0; font-size: 10.5px; }
  th { text-align: left; border-bottom: 1px solid #ddd; }
  .right { text-align: right; }
  .totals td { padding: 2px 0; }
  .grand { font-weight: 700; font-size: 13px; border-top: 1px solid #000; padding-top: 4px; }
  .footer { margin-top: 10px; text-align: center; color: #555; font-size: 10px; }
  .qr { margin-top: 6px; }
</style>
</head>
<body>
  <div class="center">
    {% if tenant.logo_url %}<img src="{{ tenant.logo_url }}" class="logo" />{% endif %}
    <div class="pharmacy">{{ tenant.pharmacy_name }}</div>
    {% if tenant.address %}<div class="muted">{{ tenant.address }}</div>{% endif %}
    {% if tenant.owner_phone %}<div class="muted">Tel: {{ tenant.owner_phone }}</div>{% endif %}
    {% if tenant.tin %}<div class="muted">TIN: {{ tenant.tin }}</div>{% endif %}
    {% if tenant.business_reg_no %}<div class="muted">Reg No: {{ tenant.business_reg_no }}</div>{% endif %}
  </div>

  {% if tenant.receipt_header %}
  <div class="center" style="margin-top:6px; font-style: italic;">{{ tenant.receipt_header }}</div>
  {% endif %}

  <hr>

  <div><strong>Receipt:</strong> {{ sale.receipt_no }}</div>
  <div><strong>Date:</strong> {{ sale.timestamp }}</div>
  <div><strong>Cashier:</strong> {{ sale.cashier_name }}</div>
  {% if sale.branch_name %}<div><strong>Branch:</strong> {{ sale.branch_name }}</div>{% endif %}
  {% if sale.customer_name %}<div><strong>Customer:</strong> {{ sale.customer_name }}</div>{% endif %}

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
    {% if sale.discount %}
    <tr><td>Discount</td><td class="right">-GH₵ {{ "%.2f"|format(sale.discount) }}</td></tr>
    {% endif %}
    <tr class="grand"><td>Total</td><td class="right">GH₵ {{ "%.2f"|format(sale.total_amount) }}</td></tr>
    <tr><td>Payment</td><td class="right">{{ sale.payment_method|upper }}</td></tr>
  </table>

  {% if qr_data_uri %}
  <div class="center qr">
    <img src="{{ qr_data_uri }}" alt="qr" style="width:90px; height:90px;" />
    <div class="muted">Scan to verify</div>
  </div>
  {% endif %}

  <div class="footer">
    {{ tenant.receipt_footer or "Thank you. Get well soon!" }}<br>
    Powered by Pharmacole
  </div>
</body>
</html>
"""


def _qr_data_uri(text: str) -> str:
    if not _HAS_QR:
        return ""
    img = qrcode.make(text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    import base64
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def render_receipt_html(tenant, sale, branch_name=None):
    qr_data_uri = ""
    if tenant and sale.get("receipt_no") and getattr(tenant, "tenant_code", None):
        verify_url = (
            f"{current_app.config['BASE_URL']}/r/{sale['receipt_no']}"
            f"?tenant={tenant.tenant_code}"
        )
        qr_data_uri = _qr_data_uri(verify_url)

    return render_template_string(
        _RECEIPT_HTML,
        tenant=tenant,
        sale=sale,
        branch_name=branch_name,
        qr_data_uri=qr_data_uri,
    )


def receipt_pdf(tenant, sale, branch_name=None) -> bytes:
    if not _HAS_WEASY:
        raise RuntimeError("WeasyPrint not installed")
    html = render_receipt_html(tenant, sale, branch_name)
    return HTML(string=html).write_pdf()
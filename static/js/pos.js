// POS cart logic — cashier/pos.html
(function () {
  "use strict";

  var cfg = window.PHARMACOLE_POS;
  if (!cfg) return;

  var cart = Array.isArray(cfg.initialCart) ? cfg.initialCart.slice() : [];
  var method = "cash";
  var $ = function (id) { return document.getElementById(id); };

  function money(n) { return "GH\u20B5 " + Number(n).toFixed(2); }

  // Add product on click (event delegation)
  var grid = $("productGrid");
  if (grid) {
    grid.addEventListener("click", function (e) {
      var card = e.target.closest(".product-card");
      if (!card) return;
      var id = card.dataset.id;
      var name = card.dataset.name;
      var price = parseFloat(card.dataset.price);
      var found = cart.find(function (i) { return i.id === id; });
      if (found) found.qty += 1;
      else cart.push({ id: id, name: name, price: price, qty: 1 });
      render();
    });
  }

  // Search filter
  var search = $("posSearch");
  if (search) {
    search.addEventListener("input", function (e) {
      var q = e.target.value.toLowerCase();
      document.querySelectorAll(".product-card").forEach(function (el) {
        el.style.display = (el.dataset.search || "").indexOf(q) !== -1 ? "" : "none";
      });
    });
  }

  // Payment method
  document.querySelectorAll(".pm").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".pm").forEach(function (x) {
        x.classList.remove("active", "border-primary", "bg-primary/5", "text-primary");
        x.classList.add("border-gray-200", "text-gray-500");
      });
      btn.classList.add("active", "border-primary", "bg-primary/5", "text-primary");
      btn.classList.remove("border-gray-200", "text-gray-500");
      method = btn.dataset.m;
    });
  });

  function render() {
    var c = $("cartItems");
    if (!c) return;
    c.querySelectorAll(".cart-line").forEach(function (el) { el.remove(); });

    if (cart.length === 0) {
      $("emptyCart").style.display = "flex";
    } else {
      $("emptyCart").style.display = "none";
    }

    var sub = 0;
    cart.forEach(function (item, idx) {
      sub += item.price * item.qty;
      var row = document.createElement("div");
      row.className = "cart-line flex items-center gap-3 p-2 rounded-lg";
      row.innerHTML = ''
        + '<div class="w-9 h-9 rounded-lg bg-teal-50 flex items-center justify-center flex-shrink-0">'
        +   '<i class="fas fa-capsules text-primary text-sm"></i>'
        + '</div>'
        + '<div class="flex-1 min-w-0">'
        +   '<p class="text-sm font-medium text-gray-800 truncate">' + escapeHtml(item.name) + '</p>'
        +   '<p class="text-xs text-gray-400">' + money(item.price) + ' each</p>'
        + '</div>'
        + '<div class="flex items-center gap-1.5">'
        +   '<button type="button" class="minus w-7 h-7 rounded-md bg-gray-100 hover:bg-gray-200 text-gray-600 flex items-center justify-center text-xs" data-i="' + idx + '">\u2212</button>'
        +   '<span class="w-6 text-center text-sm font-semibold text-gray-700">' + item.qty + '</span>'
        +   '<button type="button" class="plus w-7 h-7 rounded-md bg-gray-100 hover:bg-gray-200 text-gray-600 flex items-center justify-center text-xs" data-i="' + idx + '">+</button>'
        + '</div>'
        + '<p class="text-sm font-bold text-gray-800 w-20 text-right">' + money(item.price * item.qty) + '</p>'
        + '<button type="button" class="del text-gray-300 hover:text-rose-500 p-1" data-i="' + idx + '"><i class="fas fa-times text-xs"></i></button>';
      c.appendChild(row);
    });

    var vat = sub * 0.05;
    var total = sub + vat;
    $("subtotal").textContent = money(sub);
    $("vat").textContent = money(vat);
    $("total").textContent = money(total);
    $("cartCount").textContent = cart.reduce(function (s, i) { return s + i.qty; }, 0);

    c.querySelectorAll(".plus").forEach(function (b) {
      b.onclick = function () { cart[b.dataset.i].qty += 1; render(); };
    });
    c.querySelectorAll(".minus").forEach(function (b) {
      b.onclick = function () {
        cart[b.dataset.i].qty -= 1;
        if (cart[b.dataset.i].qty <= 0) cart.splice(b.dataset.i, 1);
        render();
      };
    });
    c.querySelectorAll(".del").forEach(function (b) {
      b.onclick = function () { cart.splice(b.dataset.i, 1); render(); };
    });
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (m) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[m];
    });
  }

  // Clear
  $("clearCartBtn").onclick = function () {
    if (!cart.length) return;
    if (confirm("Clear the current order?")) { cart.length = 0; render(); }
  };

  // Hold
  $("holdBtn").onclick = function () {
    if (!cart.length) { alert("Cart is empty."); return; }
    var label = prompt("Label for held order (optional):", "");
    if (label === null) return;

    fetch(cfg.holdUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-CSRFToken": cfg.csrfToken
      },
      body: JSON.stringify({ items: cart, label: label })
    })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.error) { alert(data.error); return; }
      cart.length = 0;
      render();
      alert("Order held. You can resume it from Held Orders.");
    })
    .catch(function () { alert("Could not hold order. Please try again."); });
  };

  // Charge
  $("chargeBtn").onclick = function () {
    if (!cart.length) { alert("Cart is empty"); return; }
    $("chargeBtn").disabled = true;
    $("chargeBtn").innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing...';

    fetch(cfg.checkoutUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-CSRFToken": cfg.csrfToken
      },
      body: JSON.stringify({ items: cart, payment_method: method })
    })
    .then(function (r) {
      var ct = r.headers.get("content-type") || "";
      if (ct.indexOf("application/json") === -1) throw new Error("Unexpected server response.");
      return r.json();
    })
    .then(function (data) {
      if (data.error) {
        alert(data.error);
        resetChargeBtn();
        return;
      }
      showReceipt(data);
      cart.length = 0;
      render();
    })
    .catch(function () {
      alert("Network error. Please try again.");
      resetChargeBtn();
    });
  };

  function resetChargeBtn() {
    $("chargeBtn").disabled = false;
    $("chargeBtn").innerHTML = '<i class="fas fa-check-circle"></i> Charge';
  }

  function showReceipt(data) {
    var html = ''
      + '<p class="text-center text-xs text-gray-400 mb-3">'
      +   'Receipt <span class="font-medium text-gray-600">' + escapeHtml(data.receipt_no) + '</span><br>'
      +   new Date().toLocaleString() + '<br>'
      +   'Cashier: ' + escapeHtml(cfg.cashierName)
      + '</p>'
      + '<div class="border-t border-b border-dashed border-gray-200 py-3 my-2 space-y-1">'
      +   data.items.map(function (i) {
            return '<div class="flex justify-between text-xs">'
              + '<span class="text-gray-600">' + escapeHtml(i.name) + ' × ' + i.qty + '</span>'
              + '<span class="font-medium">' + money(i.line_subtotal) + '</span>'
              + '</div>';
          }).join("")
      + '</div>'
      + '<div class="space-y-1 text-xs">'
      +   '<div class="flex justify-between text-gray-500"><span>Subtotal</span><span>' + money(data.subtotal) + '</span></div>'
      +   '<div class="flex justify-between text-gray-500"><span>VAT</span><span>' + money(data.vat) + '</span></div>'
      +   '<div class="flex justify-between text-base font-bold text-gray-800 pt-2 border-t border-gray-200 mt-2">'
      +     '<span>Total</span><span class="text-primary">' + money(data.total) + '</span>'
      +   '</div>'
      +   '<div class="flex justify-between text-xs text-gray-500 pt-1">'
      +     '<span>Payment</span><span class="font-medium text-gray-700">' + escapeHtml(method) + '</span>'
      +   '</div>'
      + '</div>'
      + '<p class="text-center text-[10px] text-gray-300 mt-4">Thank you. Get well soon!</p>';

    $("receiptBody").innerHTML = html;
    $("receiptModal").classList.remove("hidden");
    $("receiptModal").classList.add("flex");
    resetChargeBtn();
  }

  window.closeReceipt = function () {
    $("receiptModal").classList.add("hidden");
    $("receiptModal").classList.remove("flex");
    // Refresh product stock quietly
    window.location.reload();
  };

  $("receiptModal").addEventListener("click", function (e) {
    if (e.target === $("receiptModal")) window.closeReceipt();
  });

  render();
})();
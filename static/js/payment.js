// Paystack inline integration for auth/payment.html
(function () {
  "use strict";

  window.initPaymentPage = function (cfg) {
    if (!cfg) return;

    var payBtn = document.getElementById("payBtn");
    var payBtnLabel = document.getElementById("payBtnLabel");
    var payError = document.getElementById("payError");
    var payErrorMsg = document.getElementById("payErrorMsg");

    function setLabel(html) { if (payBtnLabel) payBtnLabel.innerHTML = html; }
    function setDisabled(d) {
      if (!payBtn) return;
      payBtn.disabled = d;
      payBtn.setAttribute("aria-busy", d ? "true" : "false");
    }
    function showError(msg) {
      if (!payError || !payErrorMsg) return;
      payErrorMsg.textContent = msg || "Could not initialize payment. Please try again.";
      payError.classList.remove("hidden");
      payError.classList.add("flex");
      clearTimeout(showError._t);
      showError._t = setTimeout(function () {
        payError.classList.add("hidden");
        payError.classList.remove("flex");
      }, 8000);
    }
    function hideError() {
      if (!payError) return;
      payError.classList.add("hidden");
      payError.classList.remove("flex");
    }
    function labelDefault() {
      return '<i class="fas fa-lock"></i> Pay GH₵ ' + (cfg.amount ? cfg.amount.toFixed(2) : '') + ' with Paystack';
    }

    if (!payBtn) return;

    payBtn.addEventListener("click", function () {
      hideError();
      setDisabled(true);
      setLabel('<i class="fas fa-spinner fa-spin"></i> Initializing...');

      fetch(cfg.initUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": cfg.csrfToken
        },
        body: JSON.stringify({ tier: cfg.tier })
      })
      .then(function (r) {
        var ct = r.headers.get("content-type") || "";
        if (ct.indexOf("application/json") === -1) throw new Error("Unexpected server response. Please try again.");
        return r.json().then(function (data) {
          if (!r.ok || data.error) throw new Error(data.error || "Could not initialize payment.");
          return data;
        });
      })
      .then(function (data) {
        if (!data.reference && !data.access_code && !data.authorization_url) {
          throw new Error("Payment provider did not return a valid response.");
        }
        setDisabled(false);
        setLabel(labelDefault());

        var amountToCharge = data.amount || cfg.amount;

        var handler = PaystackPop.setup({
          key: cfg.publicKey,
          email: cfg.email,
          amount: Math.round(amountToCharge * 100),
          currency: "GHS",
          ref: data.reference,
          metadata: {
            tenant_code: cfg.tenantCode,
            tier: data.tier || cfg.tier,
            custom_fields: [
              { display_name: "Tenant", variable_name: "tenant_code", value: cfg.tenantCode },
              { display_name: "Tier", variable_name: "tier", value: data.tier || cfg.tier }
            ]
          },
          callback: function (response) {
            setDisabled(true);
            setLabel('<i class="fas fa-spinner fa-spin"></i> Verifying payment...');

            fetch(cfg.verifyUrl + "?reference=" + encodeURIComponent(response.reference), {
              method: "POST",
              credentials: "same-origin",
              headers: {
                "Accept": "application/json",
                "X-CSRFToken": cfg.csrfToken
              }
            })
            .then(function (r) { return r.json(); })
            .then(function (v) {
              if (v && v.ok) {
                window.location.href = cfg.dashUrl;
              } else {
                showError((v && v.error) || "Verification failed. Contact support if you were charged.");
                setLabel('<i class="fas fa-lock"></i> Retry payment');
                setDisabled(false);
              }
            })
            .catch(function () {
              showError("Could not verify payment. Contact support if you were charged.");
              setLabel('<i class="fas fa-lock"></i> Retry payment');
              setDisabled(false);
            });
          },
          onClose: function () {
            setLabel(labelDefault());
            setDisabled(false);
          }
        });
        handler.openIframe();
      })
      .catch(function (err) {
        console.error("[Paystack init]", err);
        showError(err.message || "Network error. Please try again.");
        setLabel('<i class="fas fa-lock"></i> Retry payment');
        setDisabled(false);
      });
    });
  };
})();
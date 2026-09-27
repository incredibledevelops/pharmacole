// Paystack inline integration for auth/payment.html
(function () {
  "use strict";

  window.initPaymentPage = function (cfg) {
    if (!cfg) return;

    var payBtn = document.getElementById("payBtn");
    var payBtnLabel = document.getElementById("payBtnLabel");
    var payError = document.getElementById("payError");
    var payErrorMsg = document.getElementById("payErrorMsg");

    var LABEL_DEFAULT = payBtnLabel.innerHTML;
    var LABEL_LOADING = '<i class="fas fa-spinner fa-spin"></i> Initializing...';
    var LABEL_VERIFY  = '<i class="fas fa-spinner fa-spin"></i> Verifying payment...';
    var LABEL_RETRY   = '<i class="fas fa-lock"></i> Retry payment';

    function setLabel(html) { payBtnLabel.innerHTML = html; }
    function setDisabled(d) {
      payBtn.disabled = d;
      payBtn.setAttribute("aria-busy", d ? "true" : "false");
    }
    function showError(msg) {
      payErrorMsg.textContent = msg || "Could not initialize payment. Please try again.";
      payError.classList.remove("hidden");
      clearTimeout(showError._t);
      showError._t = setTimeout(function () { payError.classList.add("hidden"); }, 8000);
    }
    function hideError() {
      payError.classList.add("hidden");
      payErrorMsg.textContent = "";
    }

    payBtn.addEventListener("click", function () {
      hideError();
      setDisabled(true);
      setLabel(LABEL_LOADING);

      fetch(cfg.initUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Accept": "application/json",
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": cfg.csrfToken
        }
      })
      .then(function (r) {
        var ct = r.headers.get("content-type") || "";
        if (ct.indexOf("application/json") === -1) {
          throw new Error("Unexpected server response. Please try again.");
        }
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
        setLabel(LABEL_DEFAULT);

        var handler = PaystackPop.setup({
          key: cfg.publicKey,
          email: cfg.email,
          amount: Math.round(cfg.amount * 100),
          currency: "GHS",
          ref: data.reference,
          metadata: {
            tenant_code: cfg.tenantCode,
            custom_fields: [
              { display_name: "Tenant", variable_name: "tenant_code", value: cfg.tenantCode }
            ]
          },
          callback: function (response) {
            setDisabled(true);
            setLabel(LABEL_VERIFY);

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
                setLabel(LABEL_RETRY);
                setDisabled(false);
              }
            })
            .catch(function () {
              showError("Could not verify payment. Contact support if you were charged.");
              setLabel(LABEL_RETRY);
              setDisabled(false);
            });
          },
          onClose: function () {
            // user closed the popup without paying — not an error, just reset
            setLabel(LABEL_DEFAULT);
            setDisabled(false);
          }
        });
        handler.openIframe();
      })
      .catch(function (err) {
        console.error("[Paystack init]", err);
        showError(err.message || "Network error. Please try again.");
        setLabel(LABEL_RETRY);
        setDisabled(false);
      });
    });
  };
})();
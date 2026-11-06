// Paystack inline integration for auth/payment.html
(function () {
  "use strict";

  function readCfg() {
    return window.PHARMACOLE_PAYMENT || {};
  }

  window.initPaymentPage = function (cfg0) {
    var payBtn = document.getElementById("payBtn");
    var payBtnLabel = document.getElementById("payBtnLabel");
    var payError = document.getElementById("payError");
    var payErrorMsg = document.getElementById("payErrorMsg");
    var paySuccess = document.getElementById("paySuccess");
    var payTimer = document.getElementById("payTimer");
    var payTimerSeconds = document.getElementById("payTimerSeconds");
    var refreshSlot = document.getElementById("refreshStatusSlot");

    var REF_KEY = "pharmacole_last_reference";
    var timerInterval = null;
    var timerStart = 0;
    var busy = false;

    function setLabel(html) { if (payBtnLabel) payBtnLabel.innerHTML = html; }
    function setDisabled(d) {
      if (!payBtn) return;
      payBtn.disabled = !!d;
      payBtn.setAttribute("aria-busy", d ? "true" : "false");
    }
    function showError(msg, hint) {
      if (!payError || !payErrorMsg) return;
      payErrorMsg.textContent = msg || "Could not initialize payment. Please try again.";
      var hintEl = document.getElementById("payErrorHint");
      if (hintEl) hintEl.textContent = hint || "";
      payError.classList.remove("hidden");
      payError.classList.add("flex");
    }
    function hideError() {
      if (!payError) return;
      payError.classList.add("hidden");
      payError.classList.remove("flex");
    }
    function showSuccess() {
      if (!paySuccess) return;
      paySuccess.classList.remove("hidden");
      paySuccess.classList.add("flex");
    }
    function labelDefault(cfg) {
      return '<i class="fas fa-lock"></i> Pay GH₵ ' +
        (cfg && cfg.amount ? cfg.amount.toFixed(2) : "") + ' with Paystack';
    }
    function startTimer() {
      if (!payTimer || !payTimerSeconds) return;
      timerStart = Date.now();
      payTimer.classList.remove("hidden");
      payTimer.classList.add("inline-flex");
      payTimerSeconds.textContent = "0s";
      clearInterval(timerInterval);
      timerInterval = setInterval(function () {
        var s = Math.floor((Date.now() - timerStart) / 1000);
        payTimerSeconds.textContent = s + "s";
      }, 1000);
    }
    function stopTimer() {
      clearInterval(timerInterval);
      if (payTimer) { payTimer.classList.add("hidden"); payTimer.classList.remove("inline-flex"); }
    }

    function rememberReference(ref) {
      try { if (ref) sessionStorage.setItem(REF_KEY, ref); } catch (e) {}
    }
    function readReference() {
      try { return sessionStorage.getItem(REF_KEY); } catch (e) { return null; }
    }
    function forgetReference() {
      try { sessionStorage.removeItem(REF_KEY); } catch (e) {}
    }

    function renderRefreshButton() {
      if (!refreshSlot) return;
      var lastRef = readReference();
      if (!lastRef) { refreshSlot.innerHTML = ""; return; }

      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "text-[11px] text-primary hover:underline font-medium inline-flex items-center gap-1";
      btn.innerHTML = '<i class="fas fa-rotate"></i> Already paid? Refresh status';

      btn.addEventListener("click", function () {
        var cfg = readCfg();
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Checking…';
        fetch(cfg.verifyUrl + "?reference=" + encodeURIComponent(lastRef), {
          method: "POST",
          credentials: "same-origin",
          headers: { "Accept": "application/json", "X-CSRFToken": cfg.csrfToken }
        })
          .then(function (r) { return r.json(); })
          .then(function (v) {
            if (v && v.ok) {
              forgetReference();
              showSuccess();
              setTimeout(function () { window.location.href = cfg.dashUrl; }, 800);
            } else {
              btn.disabled = false;
              btn.innerHTML = '<i class="fas fa-rotate"></i> Already paid? Refresh status';
              showError((v && v.error) || "No successful payment found yet.");
            }
          })
          .catch(function () {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-rotate"></i> Already paid? Refresh status';
            showError("Network error while checking payment status.");
          });
      });
      refreshSlot.innerHTML = "";
      refreshSlot.appendChild(btn);
    }
    renderRefreshButton();

    if (!payBtn) return;

    // The one and only click handler.
    payBtn.addEventListener("click", function () {
      if (busy) return;
      busy = true;
      hideError();

      // Always re-read cfg — the inline tier picker mutates it.
      var cfg = readCfg();

      setDisabled(true);
      setLabel('<i class="fas fa-spinner fa-spin"></i> Initializing...');
      startTimer();

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
        if (data.reference) rememberReference(data.reference);

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
            setLabel('<i class="fas fa-spinner fa-spin"></i> Verifying payment...');
            fetch(cfg.verifyUrl + "?reference=" + encodeURIComponent(response.reference), {
              method: "POST",
              credentials: "same-origin",
              headers: { "Accept": "application/json", "X-CSRFToken": cfg.csrfToken }
            })
              .then(function (r) { return r.json(); })
              .then(function (v) {
                if (v && v.ok) {
                  forgetReference();
                  showSuccess();
                  stopTimer();
                  setTimeout(function () { window.location.href = cfg.dashUrl; }, 800);
                } else {
                  showError((v && v.error) || "Verification failed. Contact support if you were charged.");
                  setLabel('<i class="fas fa-lock"></i> Retry payment');
                  setDisabled(false);
                  busy = false;
                  stopTimer();
                  renderRefreshButton();
                }
              })
              .catch(function () {
                showError("Could not verify payment. Contact support if you were charged.");
                setLabel('<i class="fas fa-lock"></i> Retry payment');
                setDisabled(false);
                busy = false;
                stopTimer();
                renderRefreshButton();
              });
          },
          onClose: function () {
            setLabel(labelDefault(cfg));
            setDisabled(false);
            busy = false;
            stopTimer();
            renderRefreshButton();
          }
        });
        handler.openIframe();
      })
      .catch(function (err) {
        console.error("[Paystack init]", err);
        showError(err.message || "Network error. Please try again.");
        setLabel('<i class="fas fa-lock"></i> Retry payment');
        setDisabled(false);
        busy = false;
        stopTimer();
      });
    });
  };
})();
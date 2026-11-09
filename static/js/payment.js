// Paystack inline V2 integration for auth/payment.html
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

    payBtn.addEventListener("click", function () {
      if (busy) return;
      busy = true;
      hideError();

      var cfg = readCfg();
      
      // Safety check for Paystack V2
      if (typeof PaystackPop === 'undefined') {
        showError("Payment system failed to load. Please disable adblockers or check your internet connection.");
        setDisabled(false);
        busy = false;
        return;
      }

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
        if (!data.access_code) {
          throw new Error("Payment provider did not return an access code.");
        }
        if (data.reference) rememberReference(data.reference);

        // --- PAYSTACK V2 IMPLEMENTATION ---
        var popup = new PaystackPop();
        popup.checkout({
          key: cfg.publicKey,
          accessCode: data.access_code,
          onSuccess: function(response) {
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
          onCancel: function() {
            setLabel(labelDefault(cfg));
            setDisabled(false);
            busy = false;
            stopTimer();
            renderRefreshButton();
          }
        });
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
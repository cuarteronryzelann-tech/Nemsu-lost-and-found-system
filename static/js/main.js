/**
 * static/js/main.js - Shared Client-Side JavaScript
 * ===================================================
 * Provides lightweight UI enhancements used across all pages:
 *   - Auto-dismiss flash messages after a timeout
 *   - Confirm dialog for destructive actions (deny, delete)
 *   - Active nav link highlighting
 *   - Form input character counters for textarea fields
 *   - Date field default to today's date
 */


/* ── Auto-dismiss Flash Messages ─────────────────────────────────────── */
/**
 * Automatically fades out and removes flash messages after 4 seconds.
 * Gives users enough time to read the message without manual closing.
 */
(function autoHideFlash() {
    const flashMessages = document.querySelectorAll(".flash");

    flashMessages.forEach(function (flash) {
        // Wait 4 seconds then fade the message out
        setTimeout(function () {
            flash.style.transition = "opacity .5s ease";
            flash.style.opacity    = "0";

            // Remove the element from DOM after fade completes
            setTimeout(function () {
                flash.remove();
            }, 500);
        }, 4000);
    });
})();


/* ── Confirm Dialog for Destructive Actions ──────────────────────────── */
/**
 * Attaches a confirmation prompt to any form or button marked with
 * the data-confirm attribute. Prevents accidental denials or deletions.
 *
 * Usage in HTML:
 *   <form data-confirm="Are you sure you want to deny this claim?">
 *   <button data-confirm="Mark as returned?">Mark Returned</button>
 */
(function attachConfirmDialogs() {
    // Confirm on form submit
    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
        form.addEventListener("submit", function (event) {
            const message = form.getAttribute("data-confirm");
            if (!window.confirm(message)) {
                event.preventDefault();  // Cancel submission if user clicks Cancel
            }
        });
    });

    // Confirm on button click (for non-form buttons)
    document.querySelectorAll("button[data-confirm]").forEach(function (btn) {
        btn.addEventListener("click", function (event) {
            const message = btn.getAttribute("data-confirm");
            if (!window.confirm(message)) {
                event.preventDefault();
                event.stopPropagation();
            }
        });
    });
})();


/* ── Active Nav Link Highlight ───────────────────────────────────────── */
/**
 * Adds an "active" class to the nav link whose href matches the
 * current page URL path. Helps users orient themselves in the system.
 */
(function highlightActiveNavLink() {
    const currentPath = window.location.pathname;

    document.querySelectorAll(".nav-link").forEach(function (link) {
        const linkPath = new URL(link.href, window.location.origin).pathname;

        // Mark as active if the link path matches the start of the current path
        if (currentPath.startsWith(linkPath) && linkPath !== "/") {
            link.classList.add("active");
            link.style.color      = "var(--color-primary)";
            link.style.fontWeight = "700";
            link.style.background = "var(--color-primary-light)";
        }
    });
})();


/* ── Textarea Character Counter ──────────────────────────────────────── */
/**
 * Shows a live character count below any textarea with the
 * data-maxlength attribute. Helps users avoid overly long descriptions.
 *
 * Usage in HTML:
 *   <textarea data-maxlength="300"></textarea>
 */
(function attachCharCounters() {
    document.querySelectorAll("textarea[data-maxlength]").forEach(function (textarea) {
        const maxLength = parseInt(textarea.getAttribute("data-maxlength"), 10);

        // Create the counter element and insert it after the textarea
        const counter      = document.createElement("small");
        counter.className  = "char-counter";
        counter.style.color = "var(--color-text-muted)";
        counter.style.fontSize = ".75rem";
        counter.textContent = `0 / ${maxLength}`;
        textarea.parentNode.insertBefore(counter, textarea.nextSibling);

        // Update the counter on every keystroke
        textarea.addEventListener("input", function () {
            const length = textarea.value.length;
            counter.textContent = `${length} / ${maxLength}`;

            // Turn the counter red when approaching or exceeding the limit
            counter.style.color = length >= maxLength
                ? "var(--color-danger)"
                : "var(--color-text-muted)";
        });
    });
})();


/* ── Auto-fill Date Fields with Today's Date ─────────────────────────── */
/**
 * Pre-fills any date input marked with data-default-today="true"
 * with the current local date (YYYY-MM-DD).
 * Students typically report items on the day they are found or lost.
 *
 * Usage in HTML:
 *   <input type="date" data-default-today="true" />
 */
(function prefillTodayDates() {
    const today = new Date().toISOString().split("T")[0];  // Format: YYYY-MM-DD

    document.querySelectorAll("input[type='date'][data-default-today='true']")
        .forEach(function (input) {
            if (!input.value) {
                input.value = today;  // Only set if not already filled
            }
        });
})();

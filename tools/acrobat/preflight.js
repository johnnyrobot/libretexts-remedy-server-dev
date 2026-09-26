// Acrobat JavaScript injected via AppleScript `do script` to run the
// "Verify compliance with PDF/UA-1" Preflight profile on the active doc and
// stash a JSON summary in the doc's `subject` metadata field so the Python
// caller can read it back via pikepdf/PyMuPDF.
//
// The PreflightResult.report({oFile:...}) call in Acrobat 26 returns the
// full XML report as a string regardless of oFile, so we parse inline.
var __out = {};
try {
    var __prof = null;
    var __n = Preflight.getNumProfiles();
    for (var __i = 0; __i < __n; __i++) {
        var __p = Preflight.getNthProfile(__i);
        if (/PDF\/UA-1/i.test(__p.description || "")) { __prof = __p; break; }
    }
    if (!__prof) {
        __out.error = "PDF/UA-1 profile not found";
    } else {
        __out.profile = __prof.name;
        var __pr = this.preflight(__prof);
        __out.totals = {
            errors: __pr.numErrors,
            warnings: __pr.numWarnings,
            infos: __pr.numInfos
        };
        // Get XML report as string (oFile is required even though no file is written)
        var __xml = String(__pr.report({oFile: "/tmp/__preflight_unused.pdf"}));
        // Parse XML inline with regex (deterministic structure)
        var __byRule = {};
        var __rx = /<result\s+severity="([^"]+)">\s*<rule>([^<]+)<\/rule>\s*(<doc\s+hits="(\d+)"|<page\s+number="(\d+)"\s+hits="(\d+)")/g;
        var __m;
        while ((__m = __rx.exec(__xml)) !== null) {
            var __sev = __m[1];
            var __rule = __m[2];
            var __isDoc = __m[4] !== undefined;
            var __hits = parseInt(__isDoc ? __m[4] : __m[6], 10) || 0;
            if (!__byRule[__rule]) __byRule[__rule] = {severity: __sev, totalHits: 0, pages: {}, docHits: 0};
            __byRule[__rule].totalHits += __hits;
            if (__isDoc) __byRule[__rule].docHits += __hits;
            else {
                var __pn = __m[5];
                __byRule[__rule].pages[__pn] = (__byRule[__rule].pages[__pn] || 0) + __hits;
            }
        }
        // Compact: rule -> totalHits only (drop per-page detail to fit in metadata)
        var __compact = {};
        for (var __k in __byRule) {
            __compact[__k] = {sev: __byRule[__k].severity, hits: __byRule[__k].totalHits};
        }
        __out.rules = __compact;
        __out.uniqueRules = Object.keys(__compact).length;
    }
} catch (e) {
    __out.exception = String(e);
}
this.subject = JSON.stringify(__out);
// Save to known output path so the wrapper can confirm
this.saveAs({cPath: "/tmp/acrobat_preflight_out.pdf"});

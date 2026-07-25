-- Open a PDF in Acrobat, run the embedded JavaScript on the active doc,
-- then close. JS stores its JSON result in the doc's `subject` metadata
-- and saves the doc to /tmp/acrobat_preflight_out.pdf.
on run argv
    set pdfPath to item 1 of argv
    set jsCode to item 2 of argv
    with timeout of 600 seconds
        tell application "Adobe Acrobat"
            activate
            open POSIX file pdfPath
            set t to 0
            repeat while (count of documents) = 0 and t < 30
                delay 0.5
                set t to t + 0.5
            end repeat
            if (count of documents) = 0 then return "ERR no_doc"
            tell active doc
                do script jsCode
            end tell
            delay 1
            close active doc saving no
        end tell
    end timeout
    return "OK"
end run

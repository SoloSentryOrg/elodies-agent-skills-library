on sanitizedStem(filePath)
    set fileName to do shell script "/usr/bin/basename " & quoted form of filePath
    if fileName ends with ".docx" then
        set fileName to text 1 thru -6 of fileName
    end if
    return do shell script "/usr/bin/printf %s " & quoted form of fileName & " | /usr/bin/tr -c 'A-Za-z0-9._-' '_'"
end sanitizedStem

on canonicalQAFolders(outputFolder)
    if outputFolder does not start with "/" then
        error "Word QA output folder must be an absolute canonical path: " & outputFolder
    end if
    try
        do shell script "/bin/test -d " & quoted form of outputFolder & " -a ! -L " & quoted form of outputFolder
    on error
        error "Word QA output folder must be an existing, non-symlink directory: " & outputFolder
    end try
    set canonicalOutput to do shell script "/bin/realpath " & quoted form of outputFolder
    if outputFolder is not canonicalOutput then
        error "Word QA output folder must be an absolute canonical path without traversal or symlinks: " & outputFolder
    end if
    if (do shell script "/usr/bin/basename " & quoted form of canonicalOutput) is not "rendered" then
        error "Word QA output folder must be the stable Word-QA/rendered folder: " & outputFolder
    end if
    set qaRoot to do shell script "/usr/bin/dirname " & quoted form of canonicalOutput
    if (do shell script "/usr/bin/basename " & quoted form of qaRoot) is not "Word-QA" then
        error "Word QA output folder must be the stable Word-QA/rendered folder: " & outputFolder
    end if
    set inputFolder to qaRoot & "/input"
    try
        do shell script "/bin/test -d " & quoted form of inputFolder & " -a ! -L " & quoted form of inputFolder
    on error
        error "Word QA input folder must be an existing, non-symlink Word-QA/input directory: " & inputFolder
    end try
    if (do shell script "/bin/realpath " & quoted form of inputFolder) is not inputFolder then
        error "Word QA input folder must not contain traversal or symlink components: " & inputFolder
    end if
    return {canonicalOutput, inputFolder}
end canonicalQAFolders

on validateReportPath(inputPath, inputFolder)
    if inputPath does not start with "/" then
        error "Word QA input must be an absolute canonical path: " & inputPath
    end if
    if inputPath does not end with ".docx" then
        error "Word QA input must have the exact .docx extension: " & inputPath
    end if
    try
        do shell script "/bin/test -f " & quoted form of inputPath & " -a ! -L " & quoted form of inputPath
    on error
        error "Word QA input must be an existing, non-symlink regular file: " & inputPath
    end try
    set canonicalInput to do shell script "/bin/realpath " & quoted form of inputPath
    if inputPath is not canonicalInput then
        error "Word QA input must be an absolute canonical path without traversal or symlinks: " & inputPath
    end if
    if (do shell script "/usr/bin/dirname " & quoted form of canonicalInput) is not inputFolder then
        error "Word QA input must be directly inside the stable Word-QA/input folder: " & inputPath
    end if
    return canonicalInput
end validateReportPath

on sha256File(filePath)
    return do shell script "/usr/bin/shasum -a 256 " & quoted form of filePath & " | /usr/bin/awk '{print $1}'"
end sha256File

on createTaskDirectory(qaRoot)
    set taskDirectory to do shell script "/usr/bin/mktemp -d " & quoted form of (qaRoot & "/.word-render.XXXXXX")
    do shell script "/bin/chmod 700 " & quoted form of taskDirectory
    return taskDirectory
end createTaskDirectory

on cleanupTaskDirectory(taskDirectory, qaRoot)
    if taskDirectory is missing value then return
    if (do shell script "/usr/bin/dirname " & quoted form of taskDirectory) is not qaRoot then
        error "Refusing to clean a Word QA task directory outside its QA root: " & taskDirectory
    end if
    if (do shell script "/usr/bin/basename " & quoted form of taskDirectory) does not start with ".word-render." then
        error "Refusing to clean an unrecognised Word QA task directory: " & taskDirectory
    end if
    do shell script "/bin/rm -rf " & quoted form of taskDirectory
end cleanupTaskDirectory

on stageReport(inputPath, expectedHash, taskDirectory, pythonPath, stagerPath)
    set stagedPath to taskDirectory & "/input.docx"
    do shell script quoted form of pythonPath & space & quoted form of stagerPath & " --input " & quoted form of inputPath & " --output " & quoted form of stagedPath & " --expected-sha256 " & quoted form of expectedHash & " --kind docx"
    return stagedPath
end stageReport

on publishOutput(temporaryOutput, outputPath)
    try
        do shell script "/bin/ln " & quoted form of temporaryOutput & space & quoted form of outputPath
    on error
        error "Word QA output appeared during rendering; refusing to overwrite: " & outputPath
    end try
    do shell script "/bin/test -s " & quoted form of outputPath
    if sha256File(temporaryOutput) is not sha256File(outputPath) then
        error "Word QA published output failed its integrity check: " & outputPath
    end if
end publishOutput

on run argv
    if (count of argv) is less than 5 or ((count of argv) - 3) mod 2 is not 0 then
        error "usage: render_reports_with_word.applescript OUTPUT_DIR PYTHON STAGER REPORT.docx SHA256 [...]"
    end if
    set qaFolders to canonicalQAFolders(item 1 of argv)
    set outputFolder to item 1 of qaFolders
    set inputFolder to item 2 of qaFolders
    set qaRoot to do shell script "/usr/bin/dirname " & quoted form of outputFolder
    set pythonPath to item 2 of argv
    set stagerPath to item 3 of argv
    do shell script "/bin/test -f " & quoted form of pythonPath & " -a ! -L " & quoted form of pythonPath & " -a -f " & quoted form of stagerPath & " -a ! -L " & quoted form of stagerPath
    set renderedReports to {}
    repeat with argumentNumber from 4 to count of argv by 2
        set inputPath to validateReportPath(item argumentNumber of argv, inputFolder)
        set expectedHash to item (argumentNumber + 1) of argv
        try
            do shell script "/usr/bin/printf %s " & quoted form of expectedHash & " | /usr/bin/grep -Eq '^[0-9a-f]{64}$'"
        on error
            error "Word QA expected SHA-256 is invalid"
        end try
        set reportStem to sanitizedStem(inputPath)
        set outputPath to outputFolder & "/" & reportStem & "-word-full.pdf"
        try
            do shell script "/bin/test ! -e " & quoted form of outputPath
        on error
            error "Word QA output already exists; refusing to overwrite: " & outputPath
        end try
        set taskDirectory to missing value
        set my openedDocument to missing value
        try
            set taskDirectory to createTaskDirectory(qaRoot)
            set stagedPath to stageReport(inputPath, expectedHash, taskDirectory, pythonPath, stagerPath)
            set temporaryOutput to taskDirectory & "/output.pdf"
            set stagedFile to POSIX file stagedPath
            with timeout of 600 seconds
                tell application "Microsoft Word"
                    open stagedFile
                    set currentDocuments to every document
                    repeat with candidateDocument in currentDocuments
                        try
                            set candidatePath to POSIX path of (full name of candidateDocument as alias)
                        on error
                            set candidatePath to ""
                        end try
                        if candidatePath is stagedPath then
                            set my openedDocument to candidateDocument
                            exit repeat
                        end if
                    end repeat
                    if my openedDocument is missing value then error "Word did not expose the unique staged QA document"
                    set reportTOCs to tables of contents of my openedDocument
                    repeat with reportTOC in reportTOCs
                        update reportTOC
                        update page numbers reportTOC
                    end repeat
                    set reportPages to compute statistics (my openedDocument) statistic statistic pages
                    save as my openedDocument file name temporaryOutput file format format PDF
                    do shell script "/bin/test -s " & quoted form of temporaryOutput
                    close my openedDocument saving no
                    set my openedDocument to missing value
                end tell
            end timeout
            publishOutput(temporaryOutput, outputPath)
            cleanupTaskDirectory(taskDirectory, qaRoot)
            set taskDirectory to missing value
            set end of renderedReports to reportStem & tab & (reportPages as text) & tab & outputPath
        on error errorMessage number errorNumber
            tell application "Microsoft Word"
                try
                    close my openedDocument saving no
                end try
            end tell
            try
                cleanupTaskDirectory(taskDirectory, qaRoot)
            end try
            error "Word render failed for " & inputPath & ": " & errorMessage number errorNumber
        end try
    end repeat
    set AppleScript's text item delimiters to linefeed
    set resultText to renderedReports as text
    set AppleScript's text item delimiters to ""
    return resultText
end run
property openedDocument : missing value

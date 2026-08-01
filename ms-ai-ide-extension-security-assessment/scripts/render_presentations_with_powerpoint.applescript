on sanitizedStem(filePath)
    set fileName to do shell script "/usr/bin/basename " & quoted form of filePath
    if fileName ends with ".pptx" then
        set fileName to text 1 thru -6 of fileName
    end if
    return do shell script "/usr/bin/printf %s " & quoted form of fileName & " | /usr/bin/tr -c 'A-Za-z0-9._-' '_'"
end sanitizedStem

on canonicalQAFolders(outputFolder)
    if outputFolder does not start with "/" then
        error "PowerPoint QA output folder must be an absolute canonical path: " & outputFolder
    end if
    try
        do shell script "/bin/test -d " & quoted form of outputFolder & " -a ! -L " & quoted form of outputFolder
    on error
        error "PowerPoint QA output folder must be an existing, non-symlink directory: " & outputFolder
    end try
    set canonicalOutput to do shell script "/bin/realpath " & quoted form of outputFolder
    if outputFolder is not canonicalOutput then
        error "PowerPoint QA output folder must be an absolute canonical path without traversal or symlinks: " & outputFolder
    end if
    if (do shell script "/usr/bin/basename " & quoted form of canonicalOutput) is not "rendered" then
        error "PowerPoint QA output folder must be the stable PowerPoint-QA/rendered folder: " & outputFolder
    end if
    set qaRoot to do shell script "/usr/bin/dirname " & quoted form of canonicalOutput
    if (do shell script "/usr/bin/basename " & quoted form of qaRoot) is not "PowerPoint-QA" then
        error "PowerPoint QA output folder must be the stable PowerPoint-QA/rendered folder: " & outputFolder
    end if
    set inputFolder to qaRoot & "/input"
    try
        do shell script "/bin/test -d " & quoted form of inputFolder & " -a ! -L " & quoted form of inputFolder
    on error
        error "PowerPoint QA input folder must be an existing, non-symlink PowerPoint-QA/input directory: " & inputFolder
    end try
    if (do shell script "/bin/realpath " & quoted form of inputFolder) is not inputFolder then
        error "PowerPoint QA input folder must not contain traversal or symlink components: " & inputFolder
    end if
    return {canonicalOutput, inputFolder}
end canonicalQAFolders

on validatePresentationPath(inputPath, inputFolder)
    if inputPath does not start with "/" then
        error "PowerPoint QA input must be an absolute canonical path: " & inputPath
    end if
    if inputPath does not end with ".pptx" then
        error "PowerPoint QA input must have the exact .pptx extension: " & inputPath
    end if
    try
        do shell script "/bin/test -f " & quoted form of inputPath & " -a ! -L " & quoted form of inputPath
    on error
        error "PowerPoint QA input must be an existing, non-symlink regular file: " & inputPath
    end try
    set canonicalInput to do shell script "/bin/realpath " & quoted form of inputPath
    if inputPath is not canonicalInput then
        error "PowerPoint QA input must be an absolute canonical path without traversal or symlinks: " & inputPath
    end if
    if (do shell script "/usr/bin/dirname " & quoted form of canonicalInput) is not inputFolder then
        error "PowerPoint QA input must be directly inside the stable PowerPoint-QA/input folder: " & inputPath
    end if
    return canonicalInput
end validatePresentationPath

on sha256File(filePath)
    return do shell script "/usr/bin/shasum -a 256 " & quoted form of filePath & " | /usr/bin/awk '{print $1}'"
end sha256File

on createTaskDirectory(qaRoot)
    set taskDirectory to do shell script "/usr/bin/mktemp -d " & quoted form of (qaRoot & "/.powerpoint-render.XXXXXX")
    do shell script "/bin/chmod 700 " & quoted form of taskDirectory
    return taskDirectory
end createTaskDirectory

on cleanupTaskDirectory(taskDirectory, qaRoot)
    if taskDirectory is missing value then return
    if (do shell script "/usr/bin/dirname " & quoted form of taskDirectory) is not qaRoot then
        error "Refusing to clean a PowerPoint QA task directory outside its QA root: " & taskDirectory
    end if
    if (do shell script "/usr/bin/basename " & quoted form of taskDirectory) does not start with ".powerpoint-render." then
        error "Refusing to clean an unrecognised PowerPoint QA task directory: " & taskDirectory
    end if
    do shell script "/bin/rm -rf " & quoted form of taskDirectory
end cleanupTaskDirectory

on stagePresentation(inputPath, expectedHash, taskDirectory, pythonPath, stagerPath)
    set stagedPath to taskDirectory & "/input.pptx"
    do shell script quoted form of pythonPath & space & quoted form of stagerPath & " --input " & quoted form of inputPath & " --output " & quoted form of stagedPath & " --expected-sha256 " & quoted form of expectedHash & " --kind pptx"
    return stagedPath
end stagePresentation

on publishOutput(temporaryOutput, outputPath)
    try
        do shell script "/bin/ln " & quoted form of temporaryOutput & space & quoted form of outputPath
    on error
        error "PowerPoint QA output appeared during rendering; refusing to overwrite: " & outputPath
    end try
    do shell script "/bin/test -s " & quoted form of outputPath
    if sha256File(temporaryOutput) is not sha256File(outputPath) then
        error "PowerPoint QA published output failed its integrity check: " & outputPath
    end if
end publishOutput

on run argv
    if (count of argv) is less than 5 or ((count of argv) - 3) mod 2 is not 0 then
        error "usage: render_presentations_with_powerpoint.applescript OUTPUT_DIR PYTHON STAGER PRESENTATION.pptx SHA256 [...]"
    end if
    set qaFolders to canonicalQAFolders(item 1 of argv)
    set outputFolder to item 1 of qaFolders
    set inputFolder to item 2 of qaFolders
    set qaRoot to do shell script "/usr/bin/dirname " & quoted form of outputFolder
    set pythonPath to item 2 of argv
    set stagerPath to item 3 of argv
    do shell script "/bin/test -f " & quoted form of pythonPath & " -a ! -L " & quoted form of pythonPath & " -a -f " & quoted form of stagerPath & " -a ! -L " & quoted form of stagerPath
    set renderedPresentations to {}
    repeat with argumentNumber from 4 to count of argv by 2
        set inputPath to validatePresentationPath(item argumentNumber of argv, inputFolder)
        set expectedHash to item (argumentNumber + 1) of argv
        try
            do shell script "/usr/bin/printf %s " & quoted form of expectedHash & " | /usr/bin/grep -Eq '^[0-9a-f]{64}$'"
        on error
            error "PowerPoint QA expected SHA-256 is invalid"
        end try
        set presentationStem to sanitizedStem(inputPath)
        set outputPath to outputFolder & "/" & presentationStem & "-powerpoint-full.pdf"
        try
            do shell script "/bin/test ! -e " & quoted form of outputPath
        on error
            error "PowerPoint QA output already exists; refusing to overwrite: " & outputPath
        end try
        set taskDirectory to missing value
        set my openedPresentation to missing value
        try
            set taskDirectory to createTaskDirectory(qaRoot)
            set stagedPath to stagePresentation(inputPath, expectedHash, taskDirectory, pythonPath, stagerPath)
            set temporaryOutput to taskDirectory & "/output.pdf"
            set stagedFile to POSIX file stagedPath
            tell application "Microsoft PowerPoint"
                open stagedFile
                set currentPresentations to every presentation
                repeat with candidatePresentation in currentPresentations
                    if (full name of candidatePresentation as text) is stagedPath then
                        set my openedPresentation to candidatePresentation
                        exit repeat
                    end if
                end repeat
                if my openedPresentation is missing value then error "PowerPoint did not expose the unique staged QA presentation"
                set presentationSlides to count slides of (my openedPresentation)
                save my openedPresentation in POSIX file temporaryOutput as save as PDF
                do shell script "/bin/test -s " & quoted form of temporaryOutput
                close my openedPresentation saving no
                set my openedPresentation to missing value
            end tell
            publishOutput(temporaryOutput, outputPath)
            cleanupTaskDirectory(taskDirectory, qaRoot)
            set taskDirectory to missing value
            set end of renderedPresentations to presentationStem & tab & (presentationSlides as text) & tab & outputPath
        on error errorMessage number errorNumber
            tell application "Microsoft PowerPoint"
                try
                    close my openedPresentation saving no
                end try
            end tell
            try
                cleanupTaskDirectory(taskDirectory, qaRoot)
            end try
            error "PowerPoint render failed for " & inputPath & ": " & errorMessage number errorNumber
        end try
    end repeat
    set AppleScript's text item delimiters to linefeed
    set resultText to renderedPresentations as text
    set AppleScript's text item delimiters to ""
    return resultText
end run
property openedPresentation : missing value

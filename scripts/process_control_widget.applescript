on run
	set dashboardUrl to "http://127.0.0.1:8765/"
	set leftPos to 1120
	set topPos to 44
	set rightPos to 1580
	set bottomPos to 940
	
	tell application "Safari"
		activate
		set newDoc to make new document with properties {URL:dashboardUrl}
		delay 0.6
		try
			set bounds of front window to {leftPos, topPos, rightPos, bottomPos}
		end try
		return newDoc
	end tell
end run

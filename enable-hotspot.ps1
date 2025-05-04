# Load Windows Runtime types needed for Mobile Hotspot control
[Windows.System.UserProfile.LockScreen, Windows.System.UserProfile, ContentType=WindowsRuntime] | Out-Null
Add-Type -AssemblyName System.Runtime.WindowsRuntime

# Helper function to await WinRT async operations
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { 
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -like 'IAsyncOperation*' 
})[0]

function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    return $netTask.Result
}

# Get current internet connection profile
$connectionProfile = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType=WindowsRuntime]::GetInternetConnectionProfile()

if (-not $connectionProfile) {
    Write-Error "No internet connection profile found."
    exit 1
}

# Create the Tethering Manager
$tetheringManager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType=WindowsRuntime]::CreateFromConnectionProfile($connectionProfile)

# Check current Hotspot (Tethering) state
$currentState = $tetheringManager.TetheringOperationalState

switch ($currentState) {
    'On' {
        Write-Output "Mobile Hotspot is already ON."
    }
    'Off' {
        Write-Output "Mobile Hotspot is OFF. Attempting to start..."
        $result = Await ($tetheringManager.StartTetheringAsync()) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])
        
        if ($result.Status -eq 'Success') {
            Write-Output "Mobile Hotspot started successfully."
        }
        else {
            Write-Error "Failed to start Mobile Hotspot. Error: $($result.Status)"
        }
    }
    default {
        Write-Output "Hotspot status is: $currentState"
    }
}

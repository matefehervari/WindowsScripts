# Load required WinRT types
[Windows.System.UserProfile.LockScreen,Windows.System.UserProfile,ContentType=WindowsRuntime] | Out-Null
Add-Type -AssemblyName System.Runtime.WindowsRuntime

# Setup the Await helper
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { 
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' 
})[0]

function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}

function AwaitWithTimeout($WinRtTask, $ResultType, $TimeoutMs) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))

    if ($netTask.Wait($TimeoutMs)) {
        return $netTask.Result
    }
    else {
        throw "Operation timed out after $TimeoutMs milliseconds."
    }
}

# Get Tethering Manager
$connectionProfile = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]::GetInternetConnectionProfile()
$tetheringManager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]::CreateFromConnectionProfile($connectionProfile)

# Check current tethering state
$currentState = $tetheringManager.TetheringOperationalState
Write-Output "Current hotspot state: $currentState"

if ($currentState -eq 'On') {
    try {
        Write-Output "Hotspot is ON, attempting to turn it OFF..."
        $stopResult = AwaitWithTimeout ($tetheringManager.StopTetheringAsync()) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult]) 10000  # 10 sec timeout

        if ($stopResult.Status -eq 'Success') {
            Write-Output "Hotspot turned off successfully."
        }
        else {
            Write-Error "Failed to stop hotspot. Error: $($stopResult.Status)"
        }
    }
    catch {
        Write-Error "⚠️ Timeout or failure during hotspot stop: $_"
    }
}
else {
    Write-Output "Hotspot is already OFF. No action taken."
}

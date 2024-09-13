Function GetNumMonitors {Get-CimInstance -Namespace root\wmi -ClassName WmiMonitorBasicdisplayParams | Measure-Object | foreach {$_.Count}}

function StartBarrierMono {
	Start-Process -windowstyle hidden -filepath "c:\program files\barrier\barriers.exe" -argumentlist "-a 192.168.0.43 -c $home\barrier\laptop-1.sgc -n endoxide-pc --disable-crypto"
}

function StartBarrierDual {
	Start-Process -windowstyle hidden -filepath "c:\program files\barrier\barriers.exe" -argumentlist "-a 192.168.0.43 -c $home\barrier\laptop-2.sgc -n endoxide-pc --disable-crypto"
}

$numMonitors = (GetNumMonitors)

function apply_barrier_change {
	Get-Process | Where {$_.name -eq "barriers"} | Stop-Process

	if ($numMonitors -eq 3) {
		StartBarrierMono
	}
	else {
		StartBarrierDual
	}
}

apply_barrier_change

while (0 -eq 0) {
	Start-Sleep -Seconds 1
	$newNumMonitors=(GetNumMonitors)

	if ($numMonitors -ne $newNumMonitors) {
		echo "num monitors changed from $numMonitors to $newNumMonitors"
		$numMonitors = $newNumMonitors
		apply_barrier_change
	}
}

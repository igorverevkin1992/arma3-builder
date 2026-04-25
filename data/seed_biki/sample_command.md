# remoteExec

## Description
Asks the server (or other clients) to execute a function or command remotely.
Replaces the deprecated BIS_fnc_MP. Honours `CfgRemoteExec` whitelists.

## Syntax
```
arguments remoteExec [order, targets, JIP]
```

## Parameters
- arguments: Anything — passed as the first argument of the called function
- order: String — name of the function or scripting command
- targets: Number | Object | Array | Side
- JIP: Boolean | String — re-execute on JIP clients

## Return value
Number — the assigned JIP id when JIP is true, otherwise nil.

## Example
```sqf
[player, "Hello"] remoteExec ["sideChat", 0, true];
```

# remoteExecCall

## Description
Synchronous variant of `remoteExec`. Use when the result must be available
immediately on the calling machine.

## Syntax
```
arguments remoteExecCall [order, targets, JIP]
```

# CBA_statemachine_fnc_create

## Description
Creates a new finite-state machine. Returns a logic object representing the FSM.

## Syntax
```
[] call CBA_statemachine_fnc_create
```

## Example
```sqf
private _sm = [] call CBA_statemachine_fnc_create;
```

# CBA_statemachine_fnc_addState

## Description
Adds a state to the FSM with optional onEnter / onExit callbacks.

## Syntax
```
[fsm, stateName, onEnter, onExit] call CBA_statemachine_fnc_addState
```

# CBA_statemachine_fnc_addTransition

## Description
Adds a transition between two existing states. The condition expression is
evaluated periodically by the CBA frame handler — there is no busy loop.

## Syntax
```
[fsm, fromState, toState, condition, onTransition] call CBA_statemachine_fnc_addTransition
```

# CBA_fnc_addPerFrameHandler

## Description
Registers a function to be called every frame (or every N seconds). Replaces
manual `while {true} do` loops.

## Syntax
```
[code, delay, params] call CBA_fnc_addPerFrameHandler
```

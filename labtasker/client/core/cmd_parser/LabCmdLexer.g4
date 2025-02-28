lexer grammar LabCmdLexer;
// Lexer Rules with Modes

// DEFAULT_MODE Lexer Rules
VARIABLE_START: '%(' -> pushMode(VARIABLE_MODE);
TEXT: .;

// VARIABLE_MODE Lexer Rules
mode VARIABLE_MODE;

VARIABLE_END: ')' -> popMode;
DOT: '.';
ID: [a-zA-Z_][a-zA-Z0-9_]*;
INT: [0-9]+;
WS: [ \t\r\n]+ -> skip;
OTHERS: .;

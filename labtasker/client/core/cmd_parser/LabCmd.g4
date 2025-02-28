parser grammar LabCmd;

options { tokenVocab=LabCmdLexer; }

// Parser Rules
command: (text | variable)* EOF;

variable: VARIABLE_START argumentList VARIABLE_END;

argumentList: argument (DOT argument)*;

argument: ID | INT;

text: TEXT;

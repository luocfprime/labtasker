# Generated from labtasker/client/core/cmd_parser/LabCmd.g4 by ANTLR 4.13.2
# encoding: utf-8
import sys
from io import StringIO

from antlr4 import *

if sys.version_info[1] > 5:
    from typing import TextIO
else:
    from typing.io import TextIO


def serializedATN():
    return [
        4,
        1,
        8,
        36,
        2,
        0,
        7,
        0,
        2,
        1,
        7,
        1,
        2,
        2,
        7,
        2,
        2,
        3,
        7,
        3,
        2,
        4,
        7,
        4,
        1,
        0,
        1,
        0,
        5,
        0,
        13,
        8,
        0,
        10,
        0,
        12,
        0,
        16,
        9,
        0,
        1,
        0,
        1,
        0,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        2,
        1,
        2,
        1,
        2,
        5,
        2,
        27,
        8,
        2,
        10,
        2,
        12,
        2,
        30,
        9,
        2,
        1,
        3,
        1,
        3,
        1,
        4,
        1,
        4,
        1,
        4,
        0,
        0,
        5,
        0,
        2,
        4,
        6,
        8,
        0,
        1,
        1,
        0,
        5,
        6,
        33,
        0,
        14,
        1,
        0,
        0,
        0,
        2,
        19,
        1,
        0,
        0,
        0,
        4,
        23,
        1,
        0,
        0,
        0,
        6,
        31,
        1,
        0,
        0,
        0,
        8,
        33,
        1,
        0,
        0,
        0,
        10,
        13,
        3,
        8,
        4,
        0,
        11,
        13,
        3,
        2,
        1,
        0,
        12,
        10,
        1,
        0,
        0,
        0,
        12,
        11,
        1,
        0,
        0,
        0,
        13,
        16,
        1,
        0,
        0,
        0,
        14,
        12,
        1,
        0,
        0,
        0,
        14,
        15,
        1,
        0,
        0,
        0,
        15,
        17,
        1,
        0,
        0,
        0,
        16,
        14,
        1,
        0,
        0,
        0,
        17,
        18,
        5,
        0,
        0,
        1,
        18,
        1,
        1,
        0,
        0,
        0,
        19,
        20,
        5,
        1,
        0,
        0,
        20,
        21,
        3,
        4,
        2,
        0,
        21,
        22,
        5,
        3,
        0,
        0,
        22,
        3,
        1,
        0,
        0,
        0,
        23,
        28,
        3,
        6,
        3,
        0,
        24,
        25,
        5,
        4,
        0,
        0,
        25,
        27,
        3,
        6,
        3,
        0,
        26,
        24,
        1,
        0,
        0,
        0,
        27,
        30,
        1,
        0,
        0,
        0,
        28,
        26,
        1,
        0,
        0,
        0,
        28,
        29,
        1,
        0,
        0,
        0,
        29,
        5,
        1,
        0,
        0,
        0,
        30,
        28,
        1,
        0,
        0,
        0,
        31,
        32,
        7,
        0,
        0,
        0,
        32,
        7,
        1,
        0,
        0,
        0,
        33,
        34,
        5,
        2,
        0,
        0,
        34,
        9,
        1,
        0,
        0,
        0,
        3,
        12,
        14,
        28,
    ]


class LabCmd(Parser):

    grammarFileName = "LabCmd.g4"

    atn = ATNDeserializer().deserialize(serializedATN())

    decisionsToDFA = [DFA(ds, i) for i, ds in enumerate(atn.decisionToState)]

    sharedContextCache = PredictionContextCache()

    literalNames = ["<INVALID>", "'%('", "<INVALID>", "')'", "'.'"]

    symbolicNames = [
        "<INVALID>",
        "VARIABLE_START",
        "TEXT",
        "VARIABLE_END",
        "DOT",
        "ID",
        "INT",
        "WS",
        "OTHERS",
    ]

    RULE_command = 0
    RULE_variable = 1
    RULE_argumentList = 2
    RULE_argument = 3
    RULE_text = 4

    ruleNames = ["command", "variable", "argumentList", "argument", "text"]

    EOF = Token.EOF
    VARIABLE_START = 1
    TEXT = 2
    VARIABLE_END = 3
    DOT = 4
    ID = 5
    INT = 6
    WS = 7
    OTHERS = 8

    def __init__(self, input: TokenStream, output: TextIO = sys.stdout):
        super().__init__(input, output)
        self.checkVersion("4.13.2")
        self._interp = ParserATNSimulator(
            self, self.atn, self.decisionsToDFA, self.sharedContextCache
        )
        self._predicates = None

    class CommandContext(ParserRuleContext):
        __slots__ = "parser"

        def __init__(
            self, parser, parent: ParserRuleContext = None, invokingState: int = -1
        ):
            super().__init__(parent, invokingState)
            self.parser = parser

        def EOF(self):
            return self.getToken(LabCmd.EOF, 0)

        def text(self, i: int = None):
            if i is None:
                return self.getTypedRuleContexts(LabCmd.TextContext)
            else:
                return self.getTypedRuleContext(LabCmd.TextContext, i)

        def variable(self, i: int = None):
            if i is None:
                return self.getTypedRuleContexts(LabCmd.VariableContext)
            else:
                return self.getTypedRuleContext(LabCmd.VariableContext, i)

        def getRuleIndex(self):
            return LabCmd.RULE_command

        def enterRule(self, listener: ParseTreeListener):
            if hasattr(listener, "enterCommand"):
                listener.enterCommand(self)

        def exitRule(self, listener: ParseTreeListener):
            if hasattr(listener, "exitCommand"):
                listener.exitCommand(self)

    def command(self):

        localctx = LabCmd.CommandContext(self, self._ctx, self.state)
        self.enterRule(localctx, 0, self.RULE_command)
        self._la = 0  # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 14
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            while _la == 1 or _la == 2:
                self.state = 12
                self._errHandler.sync(self)
                token = self._input.LA(1)
                if token in [2]:
                    self.state = 10
                    self.text()
                    pass
                elif token in [1]:
                    self.state = 11
                    self.variable()
                    pass
                else:
                    raise NoViableAltException(self)

                self.state = 16
                self._errHandler.sync(self)
                _la = self._input.LA(1)

            self.state = 17
            self.match(LabCmd.EOF)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx

    class VariableContext(ParserRuleContext):
        __slots__ = "parser"

        def __init__(
            self, parser, parent: ParserRuleContext = None, invokingState: int = -1
        ):
            super().__init__(parent, invokingState)
            self.parser = parser

        def VARIABLE_START(self):
            return self.getToken(LabCmd.VARIABLE_START, 0)

        def argumentList(self):
            return self.getTypedRuleContext(LabCmd.ArgumentListContext, 0)

        def VARIABLE_END(self):
            return self.getToken(LabCmd.VARIABLE_END, 0)

        def getRuleIndex(self):
            return LabCmd.RULE_variable

        def enterRule(self, listener: ParseTreeListener):
            if hasattr(listener, "enterVariable"):
                listener.enterVariable(self)

        def exitRule(self, listener: ParseTreeListener):
            if hasattr(listener, "exitVariable"):
                listener.exitVariable(self)

    def variable(self):

        localctx = LabCmd.VariableContext(self, self._ctx, self.state)
        self.enterRule(localctx, 2, self.RULE_variable)
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 19
            self.match(LabCmd.VARIABLE_START)
            self.state = 20
            self.argumentList()
            self.state = 21
            self.match(LabCmd.VARIABLE_END)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx

    class ArgumentListContext(ParserRuleContext):
        __slots__ = "parser"

        def __init__(
            self, parser, parent: ParserRuleContext = None, invokingState: int = -1
        ):
            super().__init__(parent, invokingState)
            self.parser = parser

        def argument(self, i: int = None):
            if i is None:
                return self.getTypedRuleContexts(LabCmd.ArgumentContext)
            else:
                return self.getTypedRuleContext(LabCmd.ArgumentContext, i)

        def DOT(self, i: int = None):
            if i is None:
                return self.getTokens(LabCmd.DOT)
            else:
                return self.getToken(LabCmd.DOT, i)

        def getRuleIndex(self):
            return LabCmd.RULE_argumentList

        def enterRule(self, listener: ParseTreeListener):
            if hasattr(listener, "enterArgumentList"):
                listener.enterArgumentList(self)

        def exitRule(self, listener: ParseTreeListener):
            if hasattr(listener, "exitArgumentList"):
                listener.exitArgumentList(self)

    def argumentList(self):

        localctx = LabCmd.ArgumentListContext(self, self._ctx, self.state)
        self.enterRule(localctx, 4, self.RULE_argumentList)
        self._la = 0  # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 23
            self.argument()
            self.state = 28
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            while _la == 4:
                self.state = 24
                self.match(LabCmd.DOT)
                self.state = 25
                self.argument()
                self.state = 30
                self._errHandler.sync(self)
                _la = self._input.LA(1)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx

    class ArgumentContext(ParserRuleContext):
        __slots__ = "parser"

        def __init__(
            self, parser, parent: ParserRuleContext = None, invokingState: int = -1
        ):
            super().__init__(parent, invokingState)
            self.parser = parser

        def ID(self):
            return self.getToken(LabCmd.ID, 0)

        def INT(self):
            return self.getToken(LabCmd.INT, 0)

        def getRuleIndex(self):
            return LabCmd.RULE_argument

        def enterRule(self, listener: ParseTreeListener):
            if hasattr(listener, "enterArgument"):
                listener.enterArgument(self)

        def exitRule(self, listener: ParseTreeListener):
            if hasattr(listener, "exitArgument"):
                listener.exitArgument(self)

    def argument(self):

        localctx = LabCmd.ArgumentContext(self, self._ctx, self.state)
        self.enterRule(localctx, 6, self.RULE_argument)
        self._la = 0  # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 31
            _la = self._input.LA(1)
            if not (_la == 5 or _la == 6):
                self._errHandler.recoverInline(self)
            else:
                self._errHandler.reportMatch(self)
                self.consume()
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx

    class TextContext(ParserRuleContext):
        __slots__ = "parser"

        def __init__(
            self, parser, parent: ParserRuleContext = None, invokingState: int = -1
        ):
            super().__init__(parent, invokingState)
            self.parser = parser

        def TEXT(self):
            return self.getToken(LabCmd.TEXT, 0)

        def getRuleIndex(self):
            return LabCmd.RULE_text

        def enterRule(self, listener: ParseTreeListener):
            if hasattr(listener, "enterText"):
                listener.enterText(self)

        def exitRule(self, listener: ParseTreeListener):
            if hasattr(listener, "exitText"):
                listener.exitText(self)

    def text(self):

        localctx = LabCmd.TextContext(self, self._ctx, self.state)
        self.enterRule(localctx, 8, self.RULE_text)
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 33
            self.match(LabCmd.TEXT)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx

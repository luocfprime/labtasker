# Generated from labtasker/client/core/cmd_parser/LabCmd.g4 by ANTLR 4.13.2
from antlr4 import *

if "." in __name__:
    from .LabCmd import LabCmd
else:
    from LabCmd import LabCmd


# This class defines a complete listener for a parse tree produced by LabCmd.
class LabCmdListener(ParseTreeListener):

    # Enter a parse tree produced by LabCmd#command.
    def enterCommand(self, ctx: LabCmd.CommandContext):
        pass

    # Exit a parse tree produced by LabCmd#command.
    def exitCommand(self, ctx: LabCmd.CommandContext):
        pass

    # Enter a parse tree produced by LabCmd#variable.
    def enterVariable(self, ctx: LabCmd.VariableContext):
        pass

    # Exit a parse tree produced by LabCmd#variable.
    def exitVariable(self, ctx: LabCmd.VariableContext):
        pass

    # Enter a parse tree produced by LabCmd#argumentList.
    def enterArgumentList(self, ctx: LabCmd.ArgumentListContext):
        pass

    # Exit a parse tree produced by LabCmd#argumentList.
    def exitArgumentList(self, ctx: LabCmd.ArgumentListContext):
        pass

    # Enter a parse tree produced by LabCmd#argument.
    def enterArgument(self, ctx: LabCmd.ArgumentContext):
        pass

    # Exit a parse tree produced by LabCmd#argument.
    def exitArgument(self, ctx: LabCmd.ArgumentContext):
        pass

    # Enter a parse tree produced by LabCmd#text.
    def enterText(self, ctx: LabCmd.TextContext):
        pass

    # Exit a parse tree produced by LabCmd#text.
    def exitText(self, ctx: LabCmd.TextContext):
        pass


del LabCmd

// Description:
// Site-local caller for parser rule tests (kql pilot: Office365). Runs on the Office365-default router in
// its own pipe, after Office365_Adjustments (priority 0) and before
// Office365_Behavior (2000), so it sees every enriched Office365 event without
// changing the standard processors. It hands the event to the channel rules of
// Office365ParserRules_local, which emit the parser rules' lines into the
// CorrelationService sink, and returns "abort" so the event goes on to the
// next pipe. It must not change obj itself: the next pipe sees the same object.
//
// Running after Office365_Adjustments means the event was already handed to its
// storing sink, so the "@behaviors" tags the channel rules add reach the stored
// event only because the job router serializes that same object when it flushes.
// Good enough for a test; a released caller calls the channel before the parser
// sinks or passes the event (see the skill, "Tag the event").

// Data input format: ({ obj, size }) or ( doc )
function main({obj, size}) {
    Platform_Channel("Office365ParserRules_local", {obj})
    return "abort"
}

"""Real 12h watchdog must reject repeated failures without declaring production GO."""
import unittest
from scripts.watchdog_autoflow import classify, BadRun
SHA="a"*40
OLD="b"*40

def run(i,conclusion="success",status="completed",sha=SHA):
    return {"databaseId":i,"status":status,"conclusion":conclusion,"headSha":sha}

class WatchdogTests(unittest.TestCase):
    def test_two_real_failures_are_blocked(self):
        x=classify([run(20,"failure"),run(19,"failure"),run(18,"success")],SHA)
        self.assertEqual(x["status"],"BLOCKED")
        self.assertEqual(x["latest_run_ids"],[20,19])
    def test_recent_success_recovers(self):
        x=classify([run(21,"success"),run(20,"failure"),run(19,"failure")],SHA)
        self.assertEqual(x["status"],"WATCHDOG_HEALTHY")
    def test_single_failure_degraded_but_no_go(self):
        x=classify([run(20,"failure"),run(19,"success")],SHA)
        self.assertEqual((x["status"],x["production_go"]),("DEGRADED","NO-GO"))
    def test_active_run_is_pending(self):
        self.assertEqual(classify([run(21,None,"in_progress")],SHA)["status"],"PENDING")
    def test_github_cli_active_empty_conclusion_is_pending(self):
        self.assertEqual(
            classify([run(21,"","in_progress")],SHA)["status"],"PENDING"
        )
    def test_active_with_false_success_is_rejected(self):
        with self.assertRaises(BadRun):
            classify([run(21,"success","in_progress")],SHA)
    def test_bootstrap_missing_source(self):
        self.assertEqual(classify([run(21,"failure",sha=OLD)],SHA)["status"],"BOOTSTRAP")
    def test_unknown_status_rejected(self):
        with self.assertRaises(BadRun):classify([run(21,"MAGIC")],SHA)
    def test_duplicate_run_ids_rejected(self):
        with self.assertRaises(BadRun):classify([run(21),run(21)],SHA)
    def test_invalid_run_sha_rejected(self):
        with self.assertRaises(BadRun):classify([run(21,sha="bad")],SHA)
    def test_cancelled_cannot_claim_healthy(self):
        self.assertEqual(classify([run(21,"cancelled")],SHA)["status"],"BLOCKED")
    def test_source_binding_blocks_stale_green_run(self):
        x=classify([run(22,"failure"),run(21,"failure"),run(20,"success",sha=OLD)],SHA)
        self.assertEqual(x["status"],"BLOCKED")

if __name__=="__main__":unittest.main()

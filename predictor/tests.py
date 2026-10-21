import json
from django.test import TestCase, Client
from django.urls import reverse
from .models import PredictionLog
from .ml.model_engine import get_iui_predictor, get_ivf_predictor

class SeparatePredictorTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_iui_predictor_engine(self):
        predictor = get_iui_predictor()
        self.assertIsNotNone(predictor.pipeline)
        sample_iui = {
            "cycle_day": 13,
            "endometrial_thickness": 9.0,
            "endometrial_pattern": "Trilaminar",
            "left_max_follicle": 14.0,
            "left_follicle_count": 2,
            "right_max_follicle": 19.5,
            "right_follicle_count": 3,
            "hcg_trigger": 1,
            "medication": "LETROZOLE"
        }
        res = predictor.predict(sample_iui)
        self.assertIn("predicted_description", res)
        self.assertEqual(res["table_source"], "iui_history")
        self.assertGreater(res["confidence"], 0)

    def test_ivf_predictor_engine(self):
        predictor = get_ivf_predictor()
        self.assertIsNotNone(predictor.pipeline)
        sample_ivf = {
            "cycle_day": 12,
            "endometrial_thickness": 10.2,
            "endometrial_pattern": "Trilaminar",
            "left_max_follicle": 17.5,
            "left_follicle_count": 8,
            "right_max_follicle": 18.5,
            "right_follicle_count": 9,
            "hcg_trigger": 1,
            "medication": "IVF Antagonist / Agonist"
        }
        res = predictor.predict(sample_ivf)
        self.assertIn("predicted_description", res)
        self.assertEqual(res["table_source"], "ivf_history")
        self.assertGreater(res["confidence"], 0)

    def test_iui_page_view(self):
        resp = self.client.get(reverse("iui_page"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "IUI Visit 2 Plan Predictor")
        self.assertContains(resp, "iui_history")

    def test_ivf_page_view(self):
        resp = self.client.get(reverse("ivf_page"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "IVF Visit 2 Plan Predictor")
        self.assertContains(resp, "ivf_history")

    def test_predict_iui_api(self):
        payload = {
            "cycle_day": 13,
            "endometrial_thickness": 9.0,
            "left_max_follicle": 14.0,
            "right_max_follicle": 19.5,
            "hcg_trigger": 1,
            "medication": "LETROZOLE"
        }
        resp = self.client.post(
            reverse("predict_iui_api"),
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        json_data = resp.json()
        self.assertEqual(json_data["status"], "success")
        self.assertIn("predicted_description", json_data["data"])
        self.assertEqual(PredictionLog.objects.filter(table_source="iui_history").count(), 1)

    def test_predict_ivf_api(self):
        payload = {
            "cycle_day": 12,
            "endometrial_thickness": 10.0,
            "left_max_follicle": 17.0,
            "right_max_follicle": 18.0,
            "hcg_trigger": 1,
            "medication": "IVF Antagonist / Agonist"
        }
        resp = self.client.post(
            reverse("predict_ivf_api"),
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        json_data = resp.json()
        self.assertEqual(json_data["status"], "success")
        self.assertIn("predicted_description", json_data["data"])
        self.assertEqual(PredictionLog.objects.filter(table_source="ivf_history").count(), 1)

    def test_predict_plan_api_json_iui(self):
        payload = {
            "treatment_type": "iui",
            "cycle_day": 2,
            "left_afc": 12,
            "right_afc": 12,
            "pcos_pattern": "1",
            "husband_factor": "Normal"
        }
        resp = self.client.post(
            reverse("predict_plan_api"),
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["suggested_plan"], "Letrozole (LTZ 5mg)")
        self.assertIn("%", data["success_rate"])
        self.assertIn("dynamic_cohort_analysis", data["data"])
        self.assertIn("clinical_rationale", data)
        self.assertIn("recommended_protocol", data)
        self.assertIn("detected_criteria", data)
        self.assertIn("predicted_treatment", data)
        self.assertIn("medicinedata", data["predicted_treatment"])
        self.assertIn("TAB LETZOL SURE SR 5", data["predicted_treatment"]["medicinedata"])
        self.assertIn("medicines", data["predicted_treatment"])
        self.assertIn("predicted_investigation", data)
        self.assertIn("investigation_tests", data["predicted_investigation"])
        self.assertIn("investigation_json", data["predicted_investigation"])
        inv_j = data["predicted_investigation"]["investigation_json"]
        self.assertIn("hystroscopy", inv_j)
        self.assertIn("laproscopy", inv_j)
        self.assertIn("hcg", inv_j)
        self.assertIn("embryo", inv_j)
        self.assertIn("predicted_protocol", data)
        self.assertIn("daily_injections", data)
        self.assertIn("description_json", data)
        self.assertIn("protocol_days", data["predicted_protocol"])
        self.assertIn("simulation", data["description_json"])

    def test_predict_plan_api_json_ivf(self):
        payload = {
            "treatment_type": "ivf",
            "cycle_no": 1,
            "cycle_day": 2,
            "left_afc": 8,
            "right_afc": 8,
            "endo_status": "Normal"
        }
        resp = self.client.post(
            reverse("predict_plan_api"),
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["suggested_plan"], "Pick Up (Oocyte Retrieval)")
        self.assertIn("predicted_treatment", data)
        self.assertIn("predicted_investigation", data)
        self.assertIn("predicted_protocol", data)
        self.assertIn("daily_injections", data)
        self.assertIn("description_json", data)
        desc_j = data["description_json"]
        self.assertIn("protocol", desc_j)
        self.assertIn("simulation", desc_j)
        self.assertIn("oe", desc_j)
        self.assertIn("1", desc_j["protocol"])
        self.assertEqual(desc_j["protocol"]["1"]["injection_name"], "HMG_FSH")
        self.assertEqual(desc_j["simulation"]["protocol"], "FSH + HMG")

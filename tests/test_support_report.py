from pathlib import Path
import tempfile
import json
import unittest
from winpilot.demo import Demo
from winpilot.server import Application


class SupportReportTests(unittest.TestCase):
    def test_report_does_not_copy_private_state(self):
        with tempfile.TemporaryDirectory() as temp:
            app=Application(Demo(),Path(__file__).resolve().parents[1]/'ui',temp,True)
            try:
                app.info={'hostname':'PRIVATE_HOST','os':'Windows 11','build':'26100','displays':[{'serial':'PRIVATE_SERIAL','name':'PRIVATE_NAME'}],'endpoints':[],'settings':{'secret':'PRIVATE_SETTING'}}
                app.workspace.value['profiles']=[{'name':'PRIVATE_PROFILE','plan':{}}]
                app.engine.state['items']=[{'kind':'audio','status':'error','message':'PRIVATE_PATH','key':'PRIVATE_DEVICE'}]
                app.tasks={'inventory':{'status':'error','details':'PRIVATE_DETAILS'}}
                report=app.post('/api/support/report',{})
                text=json.dumps(report)
                self.assertNotIn('PRIVATE_',text);self.assertNotIn(app.token,text)
                self.assertEqual(report['devices']['displays'],1)
                self.assertEqual(report['last_run']['items'][0]['status'],'error')
            finally:app.pc.close();app.toolbox.close()

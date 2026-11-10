"""Regressions for audio reservations, erased recordings and saved device choices."""
from pathlib import Path
import tempfile,threading,time,unittest
from winpilot.server import Application
from winpilot.demo import Demo
from winpilot.workspace import ui_preferences

class Interactions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Application(Demo(),Path(__file__).parents[1]/'ui',self.tmp.name,True);self.app.info=self.app.backend.inventory();self.release=threading.Event()
    def tearDown(self):
        self.release.set()
        end=time.monotonic()+3
        while any(t['status']=='running' for t in self.app.tasks.values()) and time.monotonic()<end:time.sleep(.01)
        self.tmp.cleanup()
    def test_audio_reservation_blocks_all_other_audio_tools(self):
        for current in ('audio_test','audio_meter','voice_playback'):
            self.app.tasks={current:{'status':'running'}}
            for following in ('audio_test','audio_meter','voice_playback'):
                with self.subTest(current=current,following=following),self.assertRaises(ValueError):self.app.task(following,lambda:None)
        self.app.tasks={}
    def test_real_running_reservation_blocks_racing_start(self):
        self.app.task('audio_test',lambda:self.release.wait(2))
        with self.assertRaises(ValueError):self.app.post('/api/audio/meter',{'id':'demo-microphone'})
        with self.assertRaises(ValueError):self.app.post('/api/care/start',{'kind':'audio'})
    def test_cannot_erase_recording_during_capture_or_playback(self):
        recording=object();self.app.care.voice=recording;self.app.care.state['running']=True
        try:
            with self.assertRaises(ValueError):self.app.post('/api/care/forget-voice',{})
        finally:self.app.care.state['running']=False
        self.app.tasks={'voice_playback':{'status':'running'}}
        with self.assertRaises(ValueError):self.app.post('/api/care/forget-voice',{})
        self.assertIs(self.app.care.voice,recording);self.app.tasks={}
        self.app.post('/api/care/forget-voice',{});self.assertIsNone(self.app.care.voice)
    def test_invalid_requests_are_validation_errors(self):
        for value in (None,[],False,'audio'):
            with self.subTest(value=value),self.assertRaises(ValueError):self.app.post('/api/audio/test',value)
    def test_unplugged_or_wrong_flow_device_is_rejected(self):
        for ident in ('gone','demo-microphone'):
            with self.subTest(ident=ident),self.assertRaises(ValueError):self.app.post('/api/audio/test',{'id':ident})
        self.assertEqual(self.app.tasks,{})
    def test_observation_requires_integer_duration(self):
        for value in (30.0,True,'30',-30,0,31):
            with self.subTest(value=value),self.assertRaises(ValueError):self.app.care.start('observe',{'seconds':value})
    def test_saved_care_choices_are_accepted(self):
        view={'careTab':'audio','careMic':'mic-2','careSpeaker':'speaker-2','careSelected':'report-2','scroll':620}
        result=ui_preferences({'views':{'care':view}});self.assertEqual(result['views']['care'],view)
    def test_unknown_saved_care_tab_is_rejected(self):
        with self.assertRaises(ValueError):ui_preferences({'views':{'care':{'careTab':'arbitrary'}}})
if __name__=='__main__':unittest.main()

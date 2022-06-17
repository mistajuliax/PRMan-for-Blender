# ##### BEGIN MIT LICENSE BLOCK #####
#
# Copyright (c) 2015 Brian Savery
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
# 
#
# ##### END MIT LICENSE BLOCK #####
#import prman
import bpy
import bpy_types
import math
import os
import time
import subprocess
from subprocess import Popen, PIPE
import mathutils
from mathutils import Matrix, Vector, Quaternion
import re

from . import bl_info

from .util import bpy_newer_257
from .util import BlenderVersionError
from .util import rib, rib_path, rib_ob_bounds
from .util import make_frame_path
from .util import init_exporter_env
from .util import get_sequence_path
from .util import user_path
from .util import get_path_list_converted
from .util import path_list_convert, guess_rmantree, set_pythonpath
from .util import get_real_path
from .util import debug
from random import randint
import sys

addon_version = bl_info['version']

# global dictionaries
from .export import write_rib, write_preview_rib, get_texture_list
from .export import get_texture_list_preview

#set pythonpath
set_pythonpath(os.path.join(guess_rmantree(), 'bin'))
import prman

def init():
    pass
    
def create(engine, data, scene, region=0, space_data=0, region_data=0):
    #TODO add support for regions (rerendering)
    engine.render_pass = RPass(scene)

def free(engine):
    if hasattr(engine, 'render_pass'):
        if engine.render_pass.is_interactive_running:
            engine.render_pass.end_interactive()
        if engine.render_pass:
            del engine.render_pass

def render(engine):
    if hasattr(engine, 'render_pass'):
        engine.render_pass.render(engine)

def reset(engine, data, scene):
    engine.render_pass.set_scene(scene)

def update(engine, data, scene):
    if engine.is_preview:
        engine.render_pass.gen_preview_rib()
    else:
        engine.render_pass.gen_rib()

#assumes you have already set the scene
def start_interactive(engine):
    engine.render_pass.start_interactive()

def update_interactive(context):
    engine.render_pass.issue_edits(context)


class RPass:    
    def __init__(self, scene):
        self.scene = scene
        init_exporter_env(scene)
        self.initialize_paths(scene)

        self.rm = scene.renderman

        self.do_render = True
        self.is_interactive_running = False
        self.options = []
        prman.Init()
        self.ri = prman.Ri()

    def __del__(self):
        del self.ri
        prman.Cleanup()


    def initialize_paths(self, scene):
        self.paths = {
            'rman_binary': scene.renderman.path_renderer,
            'path_texture_optimiser': scene.renderman.path_texture_optimiser,
            'rmantree': scene.renderman.path_rmantree,
        }

        self.paths['rib_output'] = user_path(scene.renderman.path_rib_output, 
                                            scene=scene)
        self.paths['texture_output'] = user_path( \
                                            scene.renderman.path_texture_output, 
                                            scene=scene)
        self.paths['export_dir'] = user_path(os.path.dirname( \
                self.paths['rib_output']), scene=scene)

        if not os.path.exists(self.paths['export_dir']):
            os.mkdir(self.paths['export_dir'])

        self.paths['render_output'] = os.path.join(self.paths['export_dir'], 
                                        'buffer.tif')

        self.paths['shader'] = get_path_list_converted(scene.renderman, \
                                                        'shader')
        self.paths['texture'] = [self.paths['texture_output']]
        #self.paths['procedural'] = get_path_list_converted(scene.renderman, 'procedural')
        #self.paths['archive'] = get_path_list_converted(scene.renderman, 'archive')

    def render(self, engine):
        DELAY = 1
        render_output = self.paths['render_output']
        if os.path.exists(render_output):
            try:
                os.remove(render_output) # so as not to load the old file
            except:
                debug("error", "Unable to remove previous render" , 
                    render_output)
                
        def format_seconds_to_hhmmss(seconds):
            hours = seconds // (60 * 60)
            seconds %= (60 * 60)
            minutes = seconds // 60
            seconds %= 60
            return "%02i:%02i:%02i" % (hours, minutes, seconds)

        def update_image():
            image_scale = 100.0 / self.scene.render.resolution_percentage
            result = engine.begin_result(0, 0, 
                self.scene.render.resolution_x * image_scale, 
                self.scene.render.resolution_y * image_scale)
            lay = result.layers[0]
            # possible the image wont load early on.
            try:
                lay.load_from_file(render_output)
            except:
                pass
            engine.end_result(result)

        #create command and start process
        options = self.options
        prman_executable = os.path.join(self.paths['rmantree'], 'bin', \
                self.paths['rman_binary'])
        if self.rm.display_driver == 'blender':
            options = options + ['-checkpoint', 
                "%.2fs" % self.rm.update_frequency, '-Progress']
        cmd = [prman_executable] + options + ["-t:%d" % self.rm.threads] + \
                [self.paths['rib_output']]
        
        cdir = os.path.dirname(self.paths['rib_output'])
        environ = os.environ.copy()
        environ['RMANTREE'] = self.paths['rmantree']

        # Launch the command to begin rendering.
        try:
            process = subprocess.Popen(cmd, cwd=cdir, 
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environ)
            isProblem = False
        except:
            engine.report({"ERROR"},
                "Problem launching PRMan from %s." % prman_executable)
            isProblem = True

        if isProblem == False:
            # Wait for the file to be created.
            t1 = time.time()
            s = '.'
            while not os.path.exists(render_output):
                engine.update_stats("", ("PRMan: Starting Rendering" + s))
                if engine.test_break():
                    try:
                        process.kill()
                    except:
                        pass
                    break

                if process.poll() != None:
                    engine.report({"ERROR"}, "PRMan: Exited")
                    break

                time.sleep(DELAY)
                s = s + '.'

            if os.path.exists(render_output):
                prev_size = -1

                # Update while rendering
                
                cnt = 0
                while True:
                    #check for progress and errors/warnings
                    line = process.stderr.readline()
                    if line and "R90000" in str(line):
                        #these come in as bytes
                        line = line.decode('utf8')
                        perc = line.rstrip(os.linesep).split()[1].strip("%%")
                        engine.update_progress(float(perc)/100.0)
                    else:
                        if line and "ERROR" in str(line):
                            engine.report({"ERROR"}, "PRMan: %s " % line)
                        elif line and "WARNING" in str(line):
                            engine.report({"WARNING"}, "PRMan: %s " % line)

                    if process.poll() is not None:
                        update_image()
                        t2 = time.time()
                        engine.report({"INFO"}, "PRMan: Done Rendering." +
                            " (elapsed time: " + 
                                format_seconds_to_hhmmss(t2-t1) + ")")
                    
                        break

                    # user exit
                    if engine.test_break():
                        try:
                            process.kill()
                        except:
                            pass
                        break
                        
                    # check if the file updated
                    new_size = os.path.getsize(render_output)

                    if new_size != prev_size:
                        update_image()
                        prev_size = new_size

                    time.sleep(DELAY)

            else:
                debug("error", "Export path [" + render_output + 
                    "] does not exist.")
        else:
            debug("error", 
                "Problem launching PRMan from %s." % prman_executable)

    def set_scene(self, scene):
        self.scene = scene

    #start the interactive session.  Basically the same as ribgen, only 
    #save the file
    def start_interactive(self):
        pass

    #search through context.scene for is_updated
    #use edit world begin
    def issue_edits(self):
        pass

    #ri.end
    def end_interactive(self):
        pass

    def gen_rib(self):
        self.convert_textures(get_texture_list(self.scene))
        write_rib(self, self.scene, self.ri)

    def gen_preview_rib(self):
        self.convert_textures(get_texture_list_preview(self.scene))
        write_preview_rib(self, self.scene, self.ri)

    def convert_textures(self, texture_list):
        if not os.path.exists(self.paths['texture_output']):
            os.mkdir(self.paths['texture_output'])

        for in_file, out_file in texture_list:
            in_file = get_real_path(in_file)
            out_file_path = os.path.join(self.paths['texture_output'], out_file)

            if os.path.isfile(out_file_path) and \
                self.rm.always_generate_textures == False and \
                os.path.getmtime(in_file) <= os.path.getmtime(out_file_path):
                debug("info", f"TEXTURE {out_file} EXISTS (or is not dirty)!")
            else:
                cmd = [os.path.join(self.paths['rmantree'], 'bin', \
                    self.paths['path_texture_optimiser']), in_file,
                    out_file_path]
                debug("info", "TXMAKE STARTED!", cmd)


                Blendcdir = bpy.path.abspath("//")
                if Blendcdir == '':
                    Blendcdir = None

                environ = os.environ.copy()
                environ['RMANTREE'] = self.paths['rmantree']
                process = subprocess.Popen(cmd, cwd=Blendcdir, 
                                        stdout=subprocess.PIPE, env=environ)
                process.communicate()






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

import bpy
import os
import subprocess

from bpy.props import PointerProperty, StringProperty, BoolProperty, EnumProperty, \
IntProperty, FloatProperty, FloatVectorProperty, CollectionProperty

from .util import init_env
from .util import getattr_recursive


from .shader_parameters import tex_source_path
from .shader_parameters import tex_optimised_path

from .export import make_optimised_texture_3dl
from .export import export_archive

from bpy_extras.io_utils import ExportHelper


class SHADING_OT_add_renderman_nodetree(bpy.types.Operator):
    ''''''
    bl_idname = "shading.add_renderman_nodetree"
    bl_label = "Add Renderman Nodetree"
    bl_description = "Add a renderman shader node tree linked to this material"

    idtype = StringProperty(name="ID Type", default="material")

    def execute(self, context):
        idtype = self.properties.idtype
        context_data = {'material':context.material, 'lamp':context.lamp }
        idblock = context_data[idtype]

        nt = bpy.data.node_groups.new(idblock.name, type='RendermanPatternGraph')
        nt.use_fake_user = True
        idblock.renderman.nodetree = nt.name

        if idtype == 'material':
            output = nt.nodes.new('RendermanOutputNode')
            default = nt.nodes.new('PxrDisneyBxdfNode')
            default.location = output.location
            default.location[0] -= 300
            nt.links.new(default.outputs[0], output.inputs[0])
        else:

            light_type = idblock.type
            light_shader = 'PxrStdAreaLightLightNode'
            if light_type == 'SUN':
                light_shader = 'PxrStdEnvDayLightLightNode'
            elif light_type == 'HEMI':
                light_shader = 'PxrStdEnvMapLightLightNode'

            output = nt.nodes.new('RendermanOutputNode')
            default = nt.nodes.new(light_shader)
            default.location = output.location
            default.location[0] -= 300
            nt.links.new(default.outputs[0], output.inputs[1])
            #default = nt.nodes.new('PxrAreaLightNode')
            #default.location = output.location
            #default.location[0] -= 300
            #nt.links.new(default.outputs[0], output.inputs[0])

        return {'FINISHED'}


class ExportRIBArchive(bpy.types.Operator, ExportHelper):
    ''''''
    bl_idname = "export_shape.rib"
    bl_label = "Export RIB Archive (.rib)"
    bl_description = "Export an object to an archived geometry file on disk"

    filename_ext = ".rib"
    filter_glob = StringProperty(default="*.rib", options={'HIDDEN'})
    
    archive_motion = BoolProperty(name='Export Motion Data', 
        description='Exports a MotionBegin/End block for any sub-frame (motion blur) animation data', default=True)
    
    animated = BoolProperty(name='Animated Frame Sequence', 
        description='Exports a sequence of rib files for a frame range', default=False)
    frame_start = IntProperty(
        name="Start Frame",
        description="The first frame of the sequence to export",
        default=1)
    frame_end = IntProperty(
        name="End Frame",
        description="The final frame of the sequence to export",
        default=1)

    @classmethod
    def poll(cls, context):
        return len(context.selected_objects) > 0

    def execute(self, context):
        export_archive(context.scene, context.selected_objects, **self.as_keywords(ignore=("check_existing", "filter_glob")))

        return {'FINISHED'}


class TEXT_OT_compile_shader(bpy.types.Operator):
    ''''''
    bl_idname = "text.compile_shader"
    bl_label = "Compile Shader"
    bl_description = "Compile a renderman shader to byte code"
    
    add_to_path = BoolProperty(name='Add shader to shader path', 
        description='Add the shader\'s directory to the shader path', default=False)
    
    @classmethod
    def poll(cls, context):
        return type(context.area.spaces.active) == bpy.types.SpaceTextEditor
    
    def draw(self, context):
        layout = self.layout
        props = self.properties
        layout.label(text="This shader's directory is not in the shader path:")
        layout.prop(props, "add_to_path")
    
    def invoke(self, context, event):
        wm = context.window_manager
        scene = context.scene
        text = context.area.spaces.active.text

        filename = bpy.path.abspath(text.filepath)
        dirname = os.path.dirname(filename)

        # check to see if this shader exists in the shader path.
        # if not, then pop up a dialog prompting to add it.
        for p in [p.name for p in scene.renderman.shader_paths]:
            if os.path.normpath(dirname) == os.path.normpath(p):
                return self.execute(context)

        return wm.invoke_props_dialog(self)
        
    def execute(self, context):
        scene = context.scene
        text = context.area.spaces.active.text
        filename = bpy.path.abspath(text.filepath)
        shader_compiler = scene.renderman.path_shader_compiler

        if self.properties.add_to_path:
            paths = scene.renderman.shader_paths
            paths.add()
            paths[scene.renderman.shader_paths_index].name = os.path.dirname(filename)

        # save shader source file first
        bpy.ops.text.save()

        # shaderdl overwrites existing files
        cmd = [shader_compiler, filename, '-d', os.path.dirname(filename)]

        if retcode := subprocess.call(cmd):
            self.report({'ERROR'}, f"Error compiling shader: {filename}")
        else:
            self.report({'INFO'}, f"Compiled shader: {filename}")

        return {'FINISHED'}


class TEXTURE_OT_convert_to_texture(bpy.types.Operator):
    ''''''
    bl_idname = "texture.convert_to_texture"
    bl_label = "Convert to Texture"
    bl_description = "Open this file path property as a texture"

    propname = StringProperty(name="Property Name",
        description="Name of the property containing the file path",
        default="")
    shader_type = StringProperty(name="Shader Type",
        description="Type of shader to refresh (eg. surface, displacement, ...)",
        default="")
    
    def switch_context(self, context, tex):
        space = context.space_data
        
        context.window_manager.prev_context = space.context
        space.context = 'TEXTURE'
        space.pin_id = tex
        space.use_pin_id = True
        

    def execute(self, context):
        space = context.space_data
        propname = self.properties.propname
        shader_type = self.properties.shader_type
        scene = context.scene

        if space.context == 'DATA':
            ptr = context.lamp.renderman
        elif space.context == 'MATERIAL':
            ptr = context.material.renderman
        elif space.context == 'WORLD':
            if shader_type in ['atmosphere', 'shader']:
                ptr = context.world.renderman
            elif shader_type == 'light':
                ptr = context.world.renderman.gi_primary
			# BBM addition end

        init_env(scene)
        sptr = get_shader_pointerproperty(ptr, shader_type)
        if sptr is None:
            return {'CANCELLED'}

        filepath = getattr(sptr, propname)
        texname = ''

        # if there's a texture with this name
        texl = [tex for tex in bpy.data.textures if tex.name == filepath]
        if len(texl) == 1:
            self.switch_context(context, texl[0])    
            return {'FINISHED'}

        # otherwise create and initialise the texture
        texname = os.path.split(bpy.path.abspath(filepath))[1]
        if texname == '': texname = "Texture"
        tex = bpy.data.textures.new(name=texname, type='IMAGE')
        tex.renderman.file_path = filepath
        tex.renderman.auto_generate_texture = True
        tex.use_fake_user = True

        if os.path.splitext(tex.renderman.file_path)[1].lower() in ('.hdr', '.exr'):
            tex.renderman.input_color_space = 'linear'
            tex.renderman.output_color_depth = 'FLOAT'

        # update the original property with Texture name
        setattr(sptr, propname, f"{tex.name}")

        self.switch_context(context, tex)
        return {'FINISHED'}


class TEXTURE_OT_generate_optimised(bpy.types.Operator):
    ''''''
    bl_idname = "texture.generate_optimised"
    bl_label = "Generate Optimised Texture"
    bl_description = "Manually generate an optimised version of this texture"

    def execute(self, context):
        tex = context.texture
        scene = context.scene
        srcpath = tex_source_path(tex, scene.frame_current)
        optpath = tex_optimised_path(tex, scene.frame_current)

        make_optimised_texture_3dl(tex, scene.renderman.path_texture_optimiser, srcpath, optpath)
        return {'FINISHED'}

class SPACE_OT_back_to_shader(bpy.types.Operator):
    ''''''
    bl_idname = "space.back_to_shader"
    bl_label = "Back to Shader Properties"
    bl_description = "Switch properties context back to previous shader property context"

    def execute(self, context):
        space = context.space_data

        space.context = context.window_manager.prev_context
        space.pin_id = None
        space.use_pin_id = False
        return {'FINISHED'}

# stupid blocking render operator for testing
class SCREEN_OT_blocking_render(bpy.types.Operator):
    ''''''
    bl_idname = "render.blocking_render"
    bl_label = "Blocking Render"

    animation = bpy.props.BoolProperty(attr="animation",
        name="Animation",
        description="Render an Animation",
        default=False)
        
    def execute(self, context):
        bpy.ops.render.render(animation=self.properties.animation)
        return {'FINISHED'}

'''
class TEXT_OT_add_inline_rib(bpy.types.Operator):
    """
    This operator is only intended for when there are no
    blender text datablocks in the file. Just for convenience
    """
    bl_label = "Add New"
    bl_idname = "text.add_inline_rib"

    context = StringProperty(
                name="Context",
                description="Name of context member to find renderman pointer in",
                default="")
    collection = StringProperty(
                name="Collection",
                description="The collection to manipulate",
                default="")

    def execute(self, context):
        if len(bpy.data.texts) > 0:
            return {'CANCELLED'}
        bpy.data.texts.new(name="Inline RIB")

        id = getattr_recursive(context, self.properties.context)
        rm = id.renderman
        collection = getattr(rm, prop_coll)
'''



# ### Yuck, this should be built in to blender...
class COLLECTION_OT_add_remove(bpy.types.Operator):
    bl_label = "Add or Remove Paths"
    bl_idname = "collection.add_remove"
    
    action = EnumProperty(
                name="Action",
                description="Either add or remove properties",
                items=[('ADD', 'Add', ''),
                        ('REMOVE', 'Remove', '')],
                default='ADD')
    context = StringProperty(
                name="Context",
                description="Name of context member to find renderman pointer in",
                default="")
    collection = StringProperty(
                name="Collection",
                description="The collection to manipulate",
                default="")
    collection_index = StringProperty(
                name="Index Property",
                description="The property used as a collection index",
                default="")
    defaultname = StringProperty(
                name="Default Name",
                description="Default name to give this collection item",
                default="")
	# BBM addition begin
    is_shader_param = BoolProperty(name='Is shader parameter', default=False)
    shader_type = StringProperty(
                name="shader type",
                default='surface')
	# BBM addition end

    def invoke(self, context, event):
        scene = context.scene
		# BBM modification
        if not self.properties.is_shader_param:
            id = getattr_recursive(context, self.properties.context)
            rm = id.renderman
        else:
            if context.active_object.name in bpy.data.lamps.keys():
                rm = bpy.data.lamps[context.active_object.name].renderman
            else:
                rm = context.active_object.active_material.renderman
            id = getattr(rm, f'{self.properties.shader_type}_shaders')
            rm = getattr(id, self.properties.context)

        prop_coll = self.properties.collection
        coll_idx = self.properties.collection_index

        collection = getattr(rm, prop_coll)
        index = getattr(rm, coll_idx)

        # otherwise just add an empty one
        if self.properties.action == 'ADD':
            collection.add()

            index += 1
            setattr(rm, coll_idx, index)
            collection[-1].name = self.properties.defaultname
			# BBM addition begin
			# if coshader array, add the selected coshader
            if self.is_shader_param:
                coshader_name = getattr(rm, f'bl_hidden_{prop_coll}_menu')
                collection[-1].name = coshader_name
        elif self.properties.action == 'REMOVE':
            collection.remove(index)
            setattr(rm, coll_idx, index-1)

        return {'FINISHED'}

# Menus
export_archive_menu_func = (lambda self, context: self.layout.operator(ExportRIBArchive.bl_idname, text="RIB Archive (.rib)"))
compile_shader_menu_func = (lambda self, context: self.layout.operator(TEXT_OT_compile_shader.bl_idname))


def register():
    bpy.types.INFO_MT_file_export.append(export_archive_menu_func)
    bpy.types.TEXT_MT_text.append(compile_shader_menu_func)
    bpy.types.TEXT_MT_toolbox.append(compile_shader_menu_func)


def unregister():
    bpy.types.INFO_MT_file_export.remove(export_archive_menu_func)
    bpy.types.TEXT_MT_text.remove(compile_shader_menu_func)
    bpy.types.TEXT_MT_toolbox.remove(compile_shader_menu_func)

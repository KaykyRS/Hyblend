<img width="1300" height="372" alt="Hyblend cover" src="https://github.com/user-attachments/assets/5e8b8d45-2db6-481b-9bf2-8e449f38b831" />

## Hyblend
Hyblend Toolkit is a plugin for animators to be able to export their animations directly to Hytale.

### Installation
To install it in Blender, it's like any other addon:

1. Go to Edit -> Preferences -> Add-ons or Get Extensions -> click the arrow in the top right corner -> Install From Disk...
2. Look for the location where you downloaded the `HyblendToolkit` zip file.
3. Select `HyblendToolkit` and click `Install From Disk`


### What does it do?

* Import Model: You can import any model directly from .blockymodel files.
   * Import Textures: When importing a .blockymodel, you can set the path to where the texture is located.
      * `To copy it easily, go to your file explorer, select your texture, hold shift and right-click, an option called "Copy as path" will show up (win 10)`
   * Create New Armature: The created model already comes with a basic armature, just the original bones.
   * Import Attachments: It's also possible to import a model as an attachment of another model.
      * `First import your base model, then select the option "Import mode: Attach to Existing Armature". Keep in mind that the attachment goes to whichever skeleton is currently selected in the viewport.`

* Import Animation (Experimental): With the model + armature imported into Blender, you can import animations from the models.
   * `Select the armature and go to "Import Animation", look for the animation of the model that was imported and click "Import Hytale Animation"`
* Export animation: Easily export animations created inside Blender.
   * `Select the armature that has the animation, click Export Animations. Select the animations you want to export and click "Export Hytale Animation".`
   * Mouth animation: For now, this only works with the Player rig I created. Download it from the download options.
* Auto-Rig (in development): If you have experience with rig creation, there's a `Rig` option, which speeds up the process by adding the MCH/CTRL/IK bones... It's still in development, recommended only for those who understand rigging.


### Requirements

* Blender 4.5 (only tested on version 4.5.12, use on later versions at your own risk.)


### Credits

* @RaoufArts (Twitter): I found this user on reddit, he had made a plugin with the same idea, but never released it. The problem is I tried reaching out and didn't get a response. But the initial idea came from him.


## Player RIG
Additionally, I'm making the Player Character rig I created available. For those who just want to create animations for the player without any headache, I've already prepared a fully functional rig with animations tested inside the game.

### What does it have?

* Bones Collections UI: A UI to reveal and hide bones, and change bone and material properties.
* IK and FK: Includes a property to switch between IK and FK.
* Mouth bone: A Viewport panel where you can control which mouth sprite appears. When exported, this data gets saved.
* Root bones: Has root bones to control groups of bones like Pelvis and Spine.


## Open letter
Being completely honest with you all, I'm not a developer. I work as a 3D rigger and animator, and for a long time I felt the lack of a Blender addon that would let us create animations for Hytale, but after all that time waiting, nobody had made one. My goal is just to help animators who wanted to have this extra option to create their animations. So to develop this addon, AI (Claude) was used, since I wouldn't have been able to make it on my own. I used my rigging and animation experience to guide it toward the result it ended up with. `NOTE: The player rig was made entirely by me from scratch.`
